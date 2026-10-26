"""WorkspaceActions exposes this feature through the permission-controlled application facade."""
from web_bridge.workspace.files import WorkspaceError

class WorkspaceActions:
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


    def local_edit(self,key):
        with self.lock:
            if self.file_operations and key in self.file_operations.items:return self.file_operations.preview(key)
            if not self.workspace or key not in self.workspace.edits:raise WorkspaceError('Unknown edit.')
            edit=self.workspace.edits[key]
            return {'edit_id':key,'path':edit['path'],'diff':edit['diff']}


    def workspace_operation(self,operation,path,destination=None,expected_sha256=None,recursive=False,trash_id=None,workspace_id=None):
        with self.lock,self.writer():
            self.require_workspace('write',workspace_id)
            if recursive and not self.policy['recursive_delete']:raise WorkspaceError('Recursive deletion must be enabled separately in local controls.')
            proposal=self.file_operations.propose(operation,path,destination,expected_sha256,recursive,trash_id)
            if self.policy['auto_operations']:proposal.update(approval_required=False,result=self.file_operations.apply(proposal['edit_id']))
            return proposal

