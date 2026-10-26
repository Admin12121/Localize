"""Local-only authority for CTF and workspace tools."""
import platform
from pathlib import Path
import re
import threading
import secrets
import hmac
from project_meta import PROJECT, VERSION
from jobs import Jobs
from project_services import ProjectServices
from file_operations import FileOperations
from command_launch import launch_command
from agent_runner import AgentRunner
import json
from workspace import Workspace, WorkspaceError

CTF_TOOLS={'list_targets','http_request','http_batch','inspect_html','session_cookies','reset_session','browser_action','request_history'}
class Companion(ProjectServices):
    def __init__(self,network,runtime):
        self.network_bridge=network;self.runtime=Path(runtime).resolve();self.lock=threading.RLock()
        self.workspace=None;self.generation=0;self.paused=False
        self.workspace_id=None
        self.policy={'ctf':True,'read':False,'write':False,'execution':False,'host':False,'network':False,'auto_container':False,'auto_write':False,'integrations':False,'auto_operations':False,'recursive_delete':False,'image':'python:3.12-alpine'}
        self.jobs=Jobs(self.runtime,self.lock,lambda generation:not self.paused and generation==self.generation)
        self.init_services()
        self.attach_network(network)

    def attach_network(self,network):
        self.network_bridge=network
        if network is not None:
            generation=self.generation
            network.cancelled=lambda:self.paused or not self.policy['ctf'] or generation!=self.generation or self.network_bridge is not network

    def stop_browser(self):
        worker=getattr(self.network_bridge,'_browser_process',None) if self.network_bridge else None
        if worker:worker.close()

    def configure(self,root='',alias='workspace',targets=None,allow_private=None,profile=None,**policy):
        validated_profile=self.validate_profile(profile) if profile is not None else None
        allowed=set(self.policy)
        if set(policy)-allowed:raise WorkspaceError('Unknown policy setting.')
        updated={**self.policy,**policy}
        for name in allowed-{'image'}:
            if type(updated[name]) is not bool:raise WorkspaceError('Permission settings must be true or false.')
        if updated['image'] not in ('python:3.12-alpine','node:24-alpine','alpine:3.21'):raise WorkspaceError('Choose one of the supported locally prepared container images.')
        selected=Workspace(root,alias) if root else None
        if selected and (selected.root==self.runtime or selected.root in self.runtime.parents or self.runtime in selected.root.parents):raise WorkspaceError('Workspace and companion runtime must be separate.')
        if (updated['read'] or updated['write'] or updated['execution']) and not selected:raise WorkspaceError('Select a local project folder first.')
        with self.lock:
            from bridge import Bridge
            previous=self.network_bridge
            network=Bridge(targets if targets is not None else dict(previous.targets) if previous else {},allow_private=allow_private if allow_private is not None else bool(previous and previous.allow_private))
            self.runner.close()
            self.generation+=1;self.jobs.revoke();self.stop_browser()
            if self.workspace:self.workspace.edits.clear()
            self.workspace=selected;self.policy=updated
            self.file_operations=FileOperations(selected,self.runtime/'file-operations') if selected else None
            self.jobs.file_operations=self.file_operations
            if selected and self.docker_project._config:
                try:self.docker_project.validate_workspace(selected)
                except WorkspaceError:self.docker_state={'configured':False,'ready':False,'error':'Docker mapping belongs to another project. Configure the selected project locally.'}
            if validated_profile is not None:
                self.profile=validated_profile;self.profile_explicit=True
                self.profile_path.write_text(json.dumps(self.profile),encoding='utf-8')
            self.runner=AgentRunner(self.tasks,self.agent_execute,self.agent_verify)
            self.workspace_id=secrets.token_urlsafe(18) if selected else None
            self.attach_network(network)
            return self.bridge_status()

    def pause(self,paused=True):
        with self.lock:
            self.runner.close()
            self.runner=AgentRunner(self.tasks,self.agent_execute,self.agent_verify)
            self.paused=bool(paused);self.generation+=1;self.jobs.revoke();self.stop_browser()
            self.workspace_id=secrets.token_urlsafe(18) if self.workspace else None
            if self.network_bridge is not None:
                from bridge import Bridge
                self.attach_network(Bridge(dict(self.network_bridge.targets),allow_private=self.network_bridge.allow_private))
            if self.workspace:self.workspace.edits.clear()
            if self.file_operations:self.file_operations.items.clear()
            return self.bridge_status()

    def bridge_status(self):
        with self.lock:
            return {'version':VERSION,'author':PROJECT['author'],'creator':PROJECT['creator'],'license':PROJECT['license'],'platform':platform.system(),'paused':self.paused,'generation':self.generation,
                    'workspace':self.workspace.alias if self.workspace else None,'workspace_id':self.workspace_id,'permissions':dict(self.policy),'docker_cli_available':bool(self.jobs.docker),
                    'pending_commands':self.jobs.pending_count(),
                    'pending_edits':(len(self.workspace.edits)+len(self.file_operations.items)) if self.workspace else 0,'profile':dict(self.profile),
                    'capabilities':{'shell_commands':True,'file_operations':True,'docker_projects':True,'selected_integrations':True,'durable_tasks':True,'local_agent':True,'chatgpt_events':False},
                    'local_controls':'Open the companion control panel on this computer to change permissions or approve operations.'}

    def require(self,permission):
        if self.paused:raise WorkspaceError('Bridge is paused locally.')
        if not self.workspace or not self.policy[permission]:raise WorkspaceError('This capability is disabled. Enable it in the local companion control panel.')
        return self.workspace

    def require_workspace(self,permission,workspace_id):
        ws=self.require(permission)
        if not isinstance(workspace_id,str) or not self.workspace_id or not hmac.compare_digest(workspace_id,self.workspace_id):raise WorkspaceError('Workspace session changed. Read bridge_status again before preparing a new request.')
        return ws
    def workspace_list(self,path='',workspace_id=None):
        with self.lock:return self.require_workspace('read',workspace_id).listing(path)
    def workspace_read(self,path,workspace_id=None):
        with self.lock:return self.require_workspace('read',workspace_id).read(path)
    def workspace_search(self,query,path='',workspace_id=None):
        with self.lock:return self.require_workspace('read',workspace_id).search(query,path)
    def workspace_edit(self,path,text,expected_sha256=None,workspace_id=None):
        with self.lock,self.writer():
            ws=self.require_workspace('write',workspace_id);proposal=ws.propose(path,text,expected_sha256)
            if self.policy['auto_write']:return {**proposal,'approval_required':False,'result':ws.apply(proposal['edit_id'])}
            return proposal
    def approve_edit(self,edit_id,allow):
        with self.lock,self.writer():
            ws=self.require('write')
            if edit_id in self.file_operations.items:
                if not allow:self.file_operations.items.pop(edit_id,None);return {'denied':True}
                return self.file_operations.apply(edit_id)
            if not allow:ws.edits.pop(edit_id,None);return {'denied':True}
            return ws.apply(edit_id)

    def command_request(self,argv=None,idempotency_key=None,cwd='',timeout_seconds=None,environment=None,workspace_id=None,command=None,shell=None):
        with self.lock:
            ws=self.require_workspace('execution',workspace_id)
            selected=environment or self.profile['environment']
            if self.profile_explicit and selected!=self.profile['environment']:raise WorkspaceError('Command environment differs from the local project profile. Change it locally first.')
            if selected=='host' and not self.policy['host']:raise WorkspaceError('Host execution is disabled locally.')
            timeout=self.profile['default_timeout'] if timeout_seconds is None else timeout_seconds
            if type(timeout) not in (int,float) or not 1<=timeout<=self.profile['max_timeout']:raise WorkspaceError('Command timeout exceeds the configured local limit.')
            selected_shell=(shell or self.profile['shell']) if command is not None else shell
            arguments=launch_command(argv,command,selected_shell,selected)
            metadata={'command':command,'shell':selected_shell} if command is not None else {}
            return self.jobs.request(arguments,cwd,timeout,selected,idempotency_key,ws,self.generation,self.policy['network'],self.policy['image'],self.policy['auto_container'],self.policy['write'],self.policy['auto_write'],metadata=metadata)

    def command_status(self,job_id,output_offset=0):
        with self.lock:
            self.require('execution');result=self.jobs.status(job_id,output_offset)
            if result.get('session_id')!=self.jobs.session_id or result['request']['generation']!=self.generation:raise WorkspaceError('This job belongs to a revoked workspace session.')
            return result
    def command_cancel(self,job_id):
        with self.lock:
            result=self.jobs.cancel(job_id)
        return {'job_id':job_id,'state':result['state']}
    def approve_command(self,job_id,allow):
        with self.lock:
            self.require('execution');return self.jobs.approve(job_id,allow)
    def local_state(self):
        with self.lock:
            return {**self.bridge_status(),'root':str(self.workspace.root) if self.workspace else '',
                    'targets':dict(self.network_bridge.targets) if self.network_bridge else {},
                    'allow_private':bool(self.network_bridge and self.network_bridge.allow_private),
                    'jobs':self.jobs.summaries(),'profile':dict(self.profile),'docker':self.docker_state,'integrations':self.integrations.status(),'runner':self.runner_state(),
                    'tasks':self.tasks.summaries(self.workspace_snapshot(),20) if self.workspace else [],
                    'edits':[{'edit_id':k,'path':v['path']} for k,v in (self.workspace.edits.items() if self.workspace else [])]+([{'edit_id':k,'path':v['path']} for k,v in self.file_operations.items.items() if v['expires']>__import__('time').monotonic()] if self.file_operations else [])}

    def local_edit(self,key):
        with self.lock:
            if self.file_operations and key in self.file_operations.items:return self.file_operations.preview(key)
            if not self.workspace or key not in self.workspace.edits:raise WorkspaceError('Unknown edit.')
            edit=self.workspace.edits[key]
            return {'edit_id':key,'path':edit['path'],'diff':edit['diff']}
    def close(self):
        self.pause(True)
        self.runner.close();self.integrations.close();self.tasks.close()
    def __getattr__(self,name):
        if name not in CTF_TOOLS:raise AttributeError(name)
        def operation(**args):
            with self.lock:
                if self.paused or not self.policy['ctf'] or self.network_bridge is None:raise WorkspaceError('CTF mode is disabled locally.')
                network=self.network_bridge;generation=self.generation
            result=getattr(network,name)(**args)
            with self.lock:
                if self.paused or generation!=self.generation:raise WorkspaceError('CTF operation was revoked locally.')
            return result
        return operation
