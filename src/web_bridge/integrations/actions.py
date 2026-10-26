"""IntegrationActions exposes this feature through the permission-controlled application facade."""
from contextlib import ExitStack
from web_bridge.workspace.files import Workspace, WorkspaceError
from web_bridge.resources import PACKAGE_ROOT

class IntegrationActions:
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
                from web_bridge.workspace.files import Workspace
                item=Workspace(PACKAGE_ROOT/'skills/project-work').read(resource)
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

