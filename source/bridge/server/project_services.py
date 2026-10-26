"""Project configuration, local integrations and resumable work authority."""
from contextlib import contextmanager,ExitStack
import json
import os
from pathlib import Path
import secrets
import threading
import time
from agent_runner import AgentRunner
from command_launch import launch_command
from docker_project import DockerProject
from file_operations import FileOperations
from integrations import Integrations
from task_store import TaskStore
from workspace import WorkspaceError

class ProjectServices:
    def init_services(self):
        self.actor=threading.local();self.file_operations=None;self.job_leases={}
        self.profile={'environment':'container','shell':'sh','default_timeout':600,'max_timeout':3600}
        self.profile_explicit=False
        self.profile_path=self.runtime/'project-profile.json'
        if self.profile_path.is_file():
            try:self.profile=self.validate_profile(json.loads(self.profile_path.read_text('utf-8')));self.profile_explicit=True
            except (ValueError,OSError):pass
        self.docker_project=DockerProject(self.runtime/'docker-project')
        self.docker_state={'configured':False,'ready':False}
        self.integrations=Integrations(self.runtime/'integrations')
        self.tasks=TaskStore(self.runtime/'tasks')
        self.runner=AgentRunner(self.tasks,self.agent_execute,self.agent_verify)
        self.jobs.project=self.docker_project
        self.jobs.on_approve=self.claim_job
        self.jobs.on_finish=self.release_job

    def validate_profile(self,value):
        if not isinstance(value,dict) or set(value)-{'environment','shell','default_timeout','max_timeout'}:raise WorkspaceError('Invalid project profile.')
        result={**getattr(self,'profile',{}),**value}
        result.setdefault('environment','container');result.setdefault('shell','powershell' if os.name=='nt' else 'sh');result.setdefault('default_timeout',600);result.setdefault('max_timeout',3600)
        if result['environment'] not in ('host','container','docker'):raise WorkspaceError('Choose host, container snapshot, or live Docker project.')
        if result['shell'] not in ('powershell','pwsh','cmd','sh','bash'):raise WorkspaceError('Choose an installed supported shell.')
        if result['environment']!='host' and result['shell'] not in ('sh','bash'):raise WorkspaceError('Linux Docker modes require sh or bash as their shell.')
        for key in ('default_timeout','max_timeout'):
            if type(result[key]) is not int or not 1<=result[key]<=3600:raise WorkspaceError('Command timeouts must be between 1 and 3600 seconds.')
        if result['default_timeout']>result['max_timeout']:raise WorkspaceError('Default timeout exceeds the maximum.')
        return result

    def workspace_snapshot(self):
        if not self.workspace or not self.workspace_id:raise WorkspaceError('Select a current project first.')
        return {'workspace_id':self.workspace_id,'root':str(self.workspace.root)}

    @contextmanager
    def writer(self):
        with self.lock:
            if self.paused:raise WorkspaceError('Bridge is paused locally.')
            identity=self.workspace_snapshot()
            if self.jobs.unresolved(self.workspace):raise WorkspaceError('Interrupted command outcome needs local review. Inspect command history and confirm the previous command is stopped before new writes.')
            owner=getattr(self.actor,'owner',None)
            borrowed=owner is not None
            if borrowed and not self.tasks.renew_workspace(identity,owner,ttl=4000):raise WorkspaceError('Agent writer lease expired or belongs to another project.')
            if not borrowed:
                owner='chat-'+secrets.token_hex(12);self.tasks.claim_workspace(identity,owner,ttl=3600)
        try:yield
        finally:
            if not borrowed:self.tasks.release_workspace(identity,owner)

    def claim_job(self,key):
        identity=self.workspace_snapshot();owner=getattr(self.actor,'owner',None)
        borrowed=owner is not None
        if not borrowed:
            owner='job-'+key;self.tasks.claim_workspace(identity,owner,ttl=4000)
        self.job_leases[key]=(identity,owner,borrowed)

    def release_job(self,key):
        lease=self.job_leases.pop(key,None)
        if lease and not lease[2]:self.tasks.release_workspace(lease[0],lease[1])

    def workspace_operation(self,operation,path,destination=None,expected_sha256=None,recursive=False,trash_id=None,workspace_id=None):
        with self.lock,self.writer():
            self.require_workspace('write',workspace_id)
            if recursive and not self.policy['recursive_delete']:raise WorkspaceError('Recursive deletion must be enabled separately in local controls.')
            proposal=self.file_operations.propose(operation,path,destination,expected_sha256,recursive,trash_id)
            if self.policy['auto_operations']:proposal.update(approval_required=False,result=self.file_operations.apply(proposal['edit_id']))
            return proposal

    def docker_status(self,workspace_id=None):
        with self.lock:
            ws=self.require_workspace('execution',workspace_id)
            if self.docker_project._config:self.docker_project.validate_workspace(ws)
        self.docker_state=self.docker_project.status()
        return self.docker_state

    def configure_docker(self,config):
        with self.lock,self.writer():
            ws=self.require('execution');self.jobs.revoke()
            self.docker_state=self.docker_project.configure(config,ws)
            return self.docker_state

    def docker_action(self,action,**arguments):
        with self.lock,self.writer():
            result=self.docker_project.action(action,self.require('execution'),**arguments)
            self.docker_state=self.docker_project.status()
            return result

    def integration_add(self,entry):
        with self.lock,self.writer():
            self.require('integrations')
            if not isinstance(entry,dict):raise WorkspaceError('Use an integration entry.')
            entries=[e for e in self.integrations.entries if e['name']!=entry.get('name')]
            return self.integrations.configure([*entries,entry])

    def integration_remove(self,name):
        with self.lock,self.writer():
            self.require('integrations')
            return self.integrations.configure([e for e in self.integrations.entries if e['name']!=name])

    def skill_list(self,workspace_id=None):
        with self.lock:
            self.require_workspace('integrations',workspace_id)
            result=self.integrations.skills();result['skills'].insert(0,{'name':'web-bridge-project-work','builtin':True})
            return result

    def skill_read(self,name,resource='SKILL.md',workspace_id=None):
        with self.lock:
            self.require_workspace('integrations',workspace_id)
            if name=='web-bridge-project-work':
                from workspace import Workspace
                item=Workspace(Path(__file__).resolve().parents[1]/'skills/project-work').read(resource)
                return {'name':name,'resource':resource,'text':item['text'],'bytes':item['bytes']}
            return self.integrations.skill_read(name,resource)

    def _mcp_access(self,workspace_id,operation):
        with ExitStack() as scope:
            with self.lock:
                self.require_workspace('integrations',workspace_id);generation=self.generation
                scope.enter_context(self.writer())
            result=operation()
            with self.lock:
                if self.paused or generation!=self.generation:raise WorkspaceError('Integration access was revoked locally.')
            return result

    def mcp_tools(self,server=None,workspace_id=None):
        return self._mcp_access(workspace_id,lambda:self.integrations.tools(server))

    def mcp_call(self,server,tool,arguments,workspace_id=None):
        return self._mcp_access(workspace_id,lambda:self.integrations.call(server,tool,arguments))

    def task_create(self,intent,checks=None,workspace_id=None):
        with self.lock:
            self.require_workspace('read',workspace_id)
            return self.tasks.create(intent,checks or [],self.workspace_snapshot())

    def task_list(self,workspace_id=None):
        with self.lock:
            ws=self.require_workspace('read',workspace_id)
            return {'tasks':self.tasks.summaries(self.workspace_snapshot(),50)}

    def task_read(self,task_id,workspace_id=None):
        with self.lock:
            ws=self.require_workspace('read',workspace_id);task=self.tasks.read(task_id)
            if not task['workspace'].get('root') or Path(task['workspace']['root'])!=ws.root:raise WorkspaceError('Task belongs to a different project.')
            return task

    def task_checkpoint(self,task_id,handoff='',status='partial',evidence=None,expected_revision=None,workspace_id=None,checks=None):
        with self.lock:
            task=self.task_read(task_id,workspace_id)
            if task['workspace']!=self.workspace_snapshot():raise WorkspaceError('Task workspace session changed; resume it through local controls.')
            if status not in ('partial','blocked','awaiting_approval','queued'):raise WorkspaceError('Completion requires task_verify; running state requires a writer lease.')
            if checks is not None:
                if expected_revision is None or not isinstance(checks,list):raise WorkspaceError('Checklist refinements need the current expected_revision and a list.')
                for old in task['checks']:
                    if not any((new==old or isinstance(old,str) and isinstance(new,dict) and new.get('label')==old or isinstance(old,dict) and isinstance(new,dict) and all(new.get(k)==v for k,v in old.items())) for new in checks):raise WorkspaceError('Existing acceptance requirements cannot be removed or weakened.')
            return self.tasks.checkpoint(task_id,status=status,handoff=handoff,evidence=evidence,expected_revision=expected_revision,checks=checks)

    def verify_saved_task(self,task,workspace):
        with self.lock:
            if self.paused or self.workspace_snapshot()!=workspace:raise WorkspaceError('Task workspace changed; verification stopped.')
            checks=task['checks'];evidence=[];remaining=[]
            for check in checks:
                try:
                    if not isinstance(check,dict):raise WorkspaceError('This checklist entry needs explicit local verification.')
                    if check.get('kind')=='file':
                        item=self.require('read').read(check['path'])
                        if 'sha256' in check and item['sha256']!=check['sha256']:raise WorkspaceError('File hash differs.')
                        if 'contains' in check and (not isinstance(check['contains'],str) or check['contains'] not in item['text']):raise WorkspaceError('Expected text is absent.')
                        evidence.append({'kind':'file','path':item['path'],'sha256':item['sha256']})
                    elif check.get('kind')=='command':
                        item=self.command_status(check['job_id'])
                        if item.get('success') is not True or item.get('exit_code')!=0:raise WorkspaceError('Command has not succeeded.')
                        evidence.append({'kind':'command','job_id':item['job_id'],'exit_code':0,'execution':item['execution']})
                    else:raise WorkspaceError('Unsupported verification check; local review is required.')
                except (ValueError,KeyError,TypeError) as error:remaining.append({'check':check,'reason':str(error)})
            return {'verified':bool(checks) and not remaining,'evidence':evidence,'remaining':remaining}

    def task_verify(self,task_id,workspace_id=None):
        with self.lock,self.writer():
            task=self.task_read(task_id,workspace_id)
            result=self.verify_saved_task(task,self.workspace_snapshot())
            if result['verified'] and task['status']!='completed':self.tasks.checkpoint(task_id,status='completed',evidence=result['evidence'],detail='Actual file/command checks passed.')
            return result

    def configure_runner(self,config):
        # Owner chooses budgets/model, but tool schemas and authority come from us.
        from bridge import TOOL_DEFINITIONS
        allowed={'workspace_list','workspace_read','workspace_search','workspace_edit','workspace_operation','command_request','command_status','command_cancel','skill_list','skill_read','mcp_tools','mcp_call','docker_status'}
        if not isinstance(config,dict) or set(config)-{'enabled','model','api_key_env','max_steps','max_seconds','max_tokens'}:raise WorkspaceError('Invalid runner configuration.')
        tools=[{'type':'function','name':t['name'],'description':t['description'],'parameters':t['inputSchema']} for t in TOOL_DEFINITIONS if t['name'] in allowed]
        readonly=['workspace_list','workspace_read','workspace_search','command_status','skill_list','skill_read','mcp_tools','docker_status']
        return self.runner.configure({**config,'tools':tools,'read_only_tools':readonly})

    def acknowledge_command_recovery(self,job_id):
        with self.lock:
            ws=self.require('execution')
            return self.jobs.acknowledge_recovery(job_id,ws,allow_unbound=True)

    def resume_task(self,task_id):
        with self.lock:
            self.require('read');task=self.tasks.read(task_id);identity=self.workspace_snapshot()
            if task['workspace']!=identity:return self.tasks.rebind(task_id,identity)
            return task

    def discard_artifact(self,job_id):
        import re,shutil
        if not isinstance(job_id,str) or not re.fullmatch(r'[0-9a-f]{32}',job_id):raise WorkspaceError('Invalid retained artifact ID.')
        with self.lock,self.writer():
            self.require('execution');item=self.jobs.items.get(job_id)
            if item and item['state'] in ('pending','approved','running'):raise WorkspaceError('Command is still active.')
            target=(self.runtime/('job-'+job_id)).resolve()
            if target.parent!=self.runtime.resolve() or target.is_symlink():raise WorkspaceError('Invalid artifact path.')
            if target.is_dir():shutil.rmtree(target)
            if item and item.get('snapshot'):item['snapshot']['retained_locally']=False;item['artifact_retained']=False
            return {'removed':True,'artifact_id':job_id}

    def complete_task_locally(self,task_id):
        with self.lock,self.writer():
            task=self.task_read(task_id,self.workspace_id)
            if task['workspace']!=self.workspace_snapshot():task=self.tasks.rebind(task_id,self.workspace_snapshot())
            return self.tasks.checkpoint(task_id,status='completed',evidence=[{'kind':'owner_review','verified_at':time.time(),'checks':task['checks']}],detail='Owner explicitly confirmed review in local controls.')

    def runner_state(self):
        result=self.runner.status()
        result['config']={key:value for key,value in result['config'].items() if key not in ('tools','read_only_tools')}
        return result

    def start_runner(self,task_id):
        with self.lock:
            self.require('read');task=self.tasks.read(task_id);identity=self.workspace_snapshot()
            if task['workspace']!=identity:self.tasks.rebind(task_id,identity)
            return self.runner.start(task_id,identity)

    def cancel_runner(self,task_id):
        owner=self.runner.status(task_id).get('owner')
        result=self.runner.cancel(task_id)
        for key,lease in list(self.job_leases.items()):
            if lease[1]==owner:self.jobs.cancel(key)
        return result

    def agent_execute(self,tool,arguments,*,task_id,workspace,owner):
        with self.lock:
            if self.paused or self.workspace_snapshot()!=workspace:raise WorkspaceError('Current project permissions changed.')
            allowed={t['name'] for t in self.runner.config['tools']}
            if tool not in allowed:raise WorkspaceError('Runner tool is not locally selected.')
        self.actor.owner=owner;active_job=None
        try:
            args=dict(arguments)
            if tool not in ('command_status','command_cancel'):args['workspace_id']=workspace['workspace_id']
            run=self.runner.runs.get(task_id)
            deadline=(run['started']+self.runner.config['max_seconds']) if run else time.monotonic()+self.profile['max_timeout']
            if tool=='command_request':
                remaining=deadline-time.monotonic()
                if remaining<1:raise WorkspaceError('Agent time budget reached before command launch.')
                args['timeout_seconds']=min(args.get('timeout_seconds') or self.profile['default_timeout'],remaining)
            result=getattr(self,tool)(**args)
            if tool=='command_request':
                active_job=result['job_id']
                while result['state'] in ('approved','running'):
                    if self.paused or self.workspace_snapshot()!=workspace:raise WorkspaceError('Project permissions changed during execution.')
                    if time.monotonic()>=deadline or run and run['cancel'].is_set():self.jobs.cancel(result['job_id'])
                    time.sleep(.1);result=self.command_status(result['job_id'])
                if result['state']=='pending':result={**result,'approval_required':True}
            return result
        finally:
            if active_job:
                item=self.jobs.items.get(active_job)
                if item and item['state'] not in ('pending','denied','expired'):
                    # Cancelled is a public outcome, not proof cleanup finished.
                    # The runner retains its lease until the owned process drains.
                    while not item['settled'].wait(.1):pass
            self.actor.owner=None

    def agent_verify(self,task,*,workspace,owner):
        self.actor.owner=owner
        try:return self.verify_saved_task(task,workspace)
        finally:self.actor.owner=None
