"""TaskActions exposes this feature through the permission-controlled application facade."""
from pathlib import Path
import time
from web_bridge.workspace.files import WorkspaceError

class TaskActions:
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
        from web_bridge.transport.rpc import TOOL_DEFINITIONS
        allowed={'workspace_list','workspace_read','workspace_search','workspace_edit','workspace_operation','command_request','command_status','command_cancel','skill_list','skill_read','mcp_tools','mcp_call','docker_status'}
        if not isinstance(config,dict) or set(config)-{'enabled','model','api_key_env','max_steps','max_seconds','max_tokens'}:raise WorkspaceError('Invalid runner configuration.')
        tools=[{'type':'function','name':t['name'],'description':t['description'],'parameters':t['inputSchema']} for t in TOOL_DEFINITIONS if t['name'] in allowed]
        readonly=['workspace_list','workspace_read','workspace_search','command_status','skill_list','skill_read','mcp_tools','docker_status']
        return self.runner.configure({**config,'tools':tools,'read_only_tools':readonly})


    def resume_task(self,task_id):
        with self.lock:
            self.require('read');task=self.tasks.read(task_id);identity=self.workspace_snapshot()
            if task['workspace']!=identity:return self.tasks.rebind(task_id,identity)
            return task


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

