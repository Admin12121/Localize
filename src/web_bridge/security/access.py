"""AccessControl exposes this feature through the permission-controlled application facade."""
from contextlib import contextmanager
import hmac
import secrets
from web_bridge.workspace.files import WorkspaceError

class AccessControl:
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


    def require(self,permission):
        if self.paused:raise WorkspaceError('Bridge is paused locally.')
        if not self.workspace or not self.policy[permission]:raise WorkspaceError('This capability is disabled. Enable it in the local companion control panel.')
        return self.workspace


    def require_workspace(self,permission,workspace_id):
        ws=self.require(permission)
        if not isinstance(workspace_id,str) or not self.workspace_id or not hmac.compare_digest(workspace_id,self.workspace_id):raise WorkspaceError('Workspace session changed. Read bridge_status again before preparing a new request.')
        return ws

