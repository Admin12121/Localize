"""Bounded workspace operations. Local policy, never model arguments, selects roots."""
from contextlib import contextmanager
import difflib
import fnmatch
import hashlib
import os
from pathlib import Path
import re
import secrets
import stat
import threading
import time

MAX_FILE = 256_000
EXCLUDED = ('.git', '.env*', '.ssh', '.aws', '.azure', '.runtime', '.venv', 'venv', '.web-bridge-*',
            'node_modules', '__pycache__', '*.pem', '*.key', 'id_rsa*', 'id_ed25519*',
            '*.p12', '*.pfx', 'credentials', 'secrets.*')
class WorkspaceError(ValueError): pass
def sha(data): return hashlib.sha256(data).hexdigest()
def linked(info): return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)

class Workspace:
    def __init__(self, root, alias='workspace'):
        source=Path(root).absolute()
        if os.name=='nt' and str(source).startswith('\\\\'):raise WorkspaceError('Choose a local project directory, not a network or device path.')
        if linked(source.lstat()) or not source.is_dir(): raise WorkspaceError('Choose a regular local directory, not a link.')
        self.root=source.resolve()
        info=self.root.stat();self.identity=(info.st_dev,info.st_ino)
        if self.root==Path(self.root.anchor) or self.root==Path.home().resolve(): raise WorkspaceError('Choose a project folder, not a drive or home directory.')
        self.alias=str(alias)[:60] or 'workspace'
        self.edits={}; self.lock=threading.RLock()

    def check_root(self):
        info=self.root.stat()
        if self.root.resolve()!=self.root or (info.st_dev,info.st_ino)!=self.identity or linked(info):raise WorkspaceError('Approved workspace moved or was replaced. Select it again locally.')

    def check_windows_handle(self,handle):
        import ctypes
        from ctypes import wintypes
        api=ctypes.WinDLL('kernel32',use_last_error=True)
        api.GetFinalPathNameByHandleW.argtypes=[wintypes.HANDLE,wintypes.LPWSTR,wintypes.DWORD,wintypes.DWORD]
        buffer=ctypes.create_unicode_buffer(32768)
        size=api.GetFinalPathNameByHandleW(handle,buffer,len(buffer),0)
        if not size or size>=len(buffer):raise WorkspaceError('Cannot verify the opened workspace path.')
        value=buffer.value
        if value.startswith('\\\\?\\'):value=value[4:]
        try:relative=Path(value).relative_to(self.root)
        except ValueError:raise WorkspaceError('Opened path is outside the approved workspace.') from None
        self.parts('' if str(relative)=='.' else relative.as_posix(),directory=True)

    def parts(self, relative, directory=False):
        if not isinstance(relative,str) or len(relative)>500: raise WorkspaceError('Invalid relative path.')
        if relative=='' and directory: return []
        if not relative or '\\' in relative or ':' in relative or relative.startswith('/') or any(ord(c)<32 for c in relative): raise WorkspaceError('Use a relative workspace path with forward slashes.')
        parts=relative.split('/')
        for part in parts:
            if part in ('','.','..') or part.endswith((' ','.')) or re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?',part): raise WorkspaceError('Unsafe path component.')
            if any(fnmatch.fnmatchcase(part.casefold(), pattern) for pattern in EXCLUDED): raise WorkspaceError('This path is excluded by the local workspace policy.')
        return parts

    @contextmanager
    def parent(self, parts):
        """POSIX descriptor walking; Windows directory handles deny rename/delete."""
        handles=[]; fd=None
        try:
            self.check_root()
            if os.name=='nt':
                import ctypes
                from ctypes import wintypes
                api=ctypes.WinDLL('kernel32',use_last_error=True)
                api.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
                api.CreateFileW.restype=wintypes.HANDLE
                api.CloseHandle.argtypes=[wintypes.HANDLE]
                current=self.root
                for item in [None]+parts:
                    if item is not None: current=current/item
                    if linked(current.lstat()) or not current.is_dir(): raise WorkspaceError('Linked directories are not allowed.')
                    handle=api.CreateFileW(str(current),0x80000000,3,None,3,0x02200000,None)
                    if handle==wintypes.HANDLE(-1).value: raise WorkspaceError('Directory is unavailable or changed.')
                    handles.append((api,handle))
                    self.check_windows_handle(handle)
                    self.check_root()
                    if linked(current.lstat()): raise WorkspaceError('Directory changed during access.')
                yield None,current
            else:
                fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
                root_info=os.fstat(fd)
                if (root_info.st_dev,root_info.st_ino)!=self.identity:raise WorkspaceError('Approved workspace was replaced.')
                for part in parts:
                    nextfd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                    os.close(fd);fd=nextfd
                yield fd,self.root.joinpath(*parts)
        except (OSError,ValueError) as exc:
            if isinstance(exc,WorkspaceError): raise
            raise WorkspaceError('Workspace path is unavailable, unsafe, or changed.') from None
        finally:
            if fd is not None: os.close(fd)
            for api,handle in reversed(handles): api.CloseHandle(handle)

    def absent_parent(self,parts):
        for index,part in enumerate(parts):
            with self.parent(parts[:index]) as (directory,parent):
                try:info=os.stat(part,dir_fd=directory,follow_symlinks=False) if directory is not None else (parent/part).lstat()
                except FileNotFoundError:return True
                if linked(info) or not stat.S_ISDIR(info.st_mode):raise WorkspaceError('Parent is not a regular directory.')
        return False

    def make_directories(self,relative):
        parts=self.parts(relative,True);created=[]
        for index,part in enumerate(parts):
            with self.parent(parts[:index]) as (directory,parent):
                try:
                    os.mkdir(part if directory is not None else parent/part,mode=0o755,dir_fd=directory)
                    created.append('/'.join(parts[:index+1]))
                except FileExistsError:pass
            with self.parent(parts[:index+1]):pass
        return created

    def _read(self, relative):
        parts=self.parts(relative)
        if self.absent_parent(parts[:-1]):return None
        with self.parent(parts[:-1]) as (directory,path):
            return self._read_at(directory,path,parts[-1])

    def _read_at(self,directory,path,leaf):
        full=path/leaf
        try:info=os.stat(leaf,dir_fd=directory,follow_symlinks=False) if directory is not None else full.lstat()
        except FileNotFoundError:return None
        if linked(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise WorkspaceError('Only regular, singly linked files are accessible.')
        if info.st_size>MAX_FILE:raise WorkspaceError('File exceeds the 256 KB limit.')
        flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0)|getattr(os,'O_BINARY',0)
        filefd=os.open(leaf if directory is not None else full,flags,dir_fd=directory)
        try:
            actual=os.fstat(filefd)
            if not stat.S_ISREG(actual.st_mode) or actual.st_nlink!=1 or (actual.st_ino,actual.st_dev)!=(info.st_ino,info.st_dev):raise WorkspaceError('File changed during access or has multiple links.')
            if os.name=='nt':
                import msvcrt
                self.check_windows_handle(msvcrt.get_osfhandle(filefd))
            with os.fdopen(filefd,'rb',closefd=False) as stream:data=stream.read(MAX_FILE+1)
            if len(data)>MAX_FILE:raise WorkspaceError('File exceeds the 256 KB limit.')
            return data
        finally:os.close(filefd)

    def read(self,path):
        data=self._read(path)
        if data is None: raise WorkspaceError('File does not exist.')
        try: text=data.decode('utf-8')
        except UnicodeDecodeError: raise WorkspaceError('Only UTF-8 text files are supported.') from None
        if '\0' in text: raise WorkspaceError('Binary files are not supported.')
        return {'path':path,'text':text,'sha256':sha(data),'bytes':len(data)}

    def listing(self,path='',omissions=None):
        parts=self.parts(path,True);entries=[];omitted=0
        with self.parent(parts) as (directory,actual):
            with os.scandir(directory if directory is not None else actual) as iterator:
                for entry in iterator:
                    relative='/'.join(parts+[entry.name])
                    try:
                        self.parts(relative)
                        info=entry.stat(follow_symlinks=False)
                        if linked(info) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)): raise WorkspaceError('Unsafe file')
                    except (OSError,WorkspaceError):
                        omitted+=1
                        if omissions is not None:omissions.append(relative)
                        continue
                    if len(entries)>=500: omitted+=1;continue
                    entries.append({'path':relative,'kind':'directory' if stat.S_ISDIR(info.st_mode) else 'file','bytes':info.st_size})
        return {'entries':sorted(entries,key=lambda x:x['path']),'omitted':omitted}

    def walk(self,omissions=None):
        stack=[''];count=0
        while stack:
            folder=stack.pop();listing=self.listing(folder,omissions)
            if listing['omitted'] and len(listing['entries'])>=500: raise WorkspaceError('Directory exceeds the 500-entry limit.')
            for entry in listing['entries']:
                count+=1
                if count>5000: raise WorkspaceError('Workspace exceeds the 5,000-entry limit.')
                if entry['kind']=='directory': stack.append(entry['path'])
                else: yield entry['path']

    def search(self,query,path=''):
        if not isinstance(query,str) or not 1<=len(query)<=200: raise WorkspaceError('Use a search string of 1–200 characters.')
        self.parts(path,True);matches=[];scanned=0
        for name in self.walk():
            if path and not name.startswith(path+'/'): continue
            try: text=self.read(name)['text']
            except WorkspaceError: continue
            scanned+=1
            for line_no,line in enumerate(text.splitlines(),1):
                if query.casefold() in line.casefold(): matches.append({'path':name,'line':line_no,'text':line[:400]})
                if len(matches)>=50: return {'matches':matches,'truncated':True,'files_scanned':scanned}
        return {'matches':matches,'truncated':False,'files_scanned':scanned}

    def propose(self,path,text,expected_sha256):
        with self.lock:
            self.parts(path)
            if not isinstance(text,str) or '\0' in text or len(text.encode())>MAX_FILE: raise WorkspaceError('Use UTF-8 text within 256 KB.')
            original=self._read(path)
            actual=sha(original) if original is not None else None
            if actual!=expected_sha256: raise WorkspaceError('File changed; read it again before editing.')
            try: before=original.decode('utf-8') if original is not None else ''
            except UnicodeDecodeError: raise WorkspaceError('Only UTF-8 text edits are supported.') from None
            diff=''.join(difflib.unified_diff(before.splitlines(True),text.splitlines(True),fromfile=path,tofile=path))
            if len(diff)>100_000: raise WorkspaceError('Diff is too large; use a smaller edit.')
            self.edits={k:v for k,v in self.edits.items() if v['expires']>time.monotonic()}
            if len(self.edits)>=20: raise WorkspaceError('Too many pending edits.')
            key=secrets.token_urlsafe(18)
            self.edits[key]={'path':path,'text':text,'expected':actual,'expires':time.monotonic()+300,'diff':diff}
            return {'edit_id':key,'path':path,'diff':diff,'expected_sha256':actual,'approval_required':True,'expires_in_seconds':300}

    def _publish_existing(self,directory,parent,leaf,temp,expected):
        """Displace only a checked source; never overwrite a competing creator.

        Windows denies writers while the native helper hashes and moves its
        pinned source. POSIX cannot exclude writers holding old descriptors:
        retain that original inode for recovery even after successful publish.
        """
        from web_bridge.workspace.operations import FileOperations
        # The shared native primitive needs only workspace, not the operation
        # registry/runtime directory used by FileOperations' public interface.
        renamer=FileOperations.__new__(FileOperations);renamer.workspace=self
        backup='.web-bridge-backup-'+secrets.token_hex(16)
        identity=renamer._native_rename(leaf,backup,directory,parent,directory,parent,('file',expected),self)
        recovery=(parent/backup).relative_to(self.root).as_posix()
        try:
            try:moved=self._read_at(directory,parent,backup) if os.name!='nt' else None
            except (OSError,WorkspaceError):moved=None
            if os.name!='nt' and (moved is None or sha(moved)!=expected):
                try:
                    renamer._native_rename(backup,leaf,directory,parent,directory,parent,sourcews=self,source_identity=identity)
                except (OSError,WorkspaceError):
                    raise WorkspaceError('File changed during edit; competing contents preserved. Recover the original locally from '+recovery+'.') from None
                raise WorkspaceError('File changed during edit; competing contents preserved at the original path.')
            info=os.stat(backup,dir_fd=directory,follow_symlinks=False) if directory is not None else (parent/backup).lstat()
            os.chmod(temp if directory is not None else parent/temp,stat.S_IMODE(info.st_mode),dir_fd=directory)
            try:
                os.link(temp if directory is not None else parent/temp,leaf if directory is not None else parent/leaf,src_dir_fd=directory,dst_dir_fd=directory,follow_symlinks=False)
            except OSError:
                raise WorkspaceError('Edit could not be published; a competing file may exist. Recover the original locally from '+recovery+'; inspect both paths before retrying.') from None
        except OSError:
            raise WorkspaceError('Edit interrupted after preserving the original. Recover it locally from '+recovery+'; inspect the requested path before retrying.') from None
        if os.name=='nt':
            try:os.unlink(parent/backup)
            except OSError:
                raise WorkspaceError('Edit was applied, but its original backup remains. Recover or remove it locally at '+recovery+'.') from None
            return None
        return recovery

    def apply(self,edit_id):
        with self.lock:
            edit=self.edits.pop(edit_id,None)
            if not edit or edit['expires']<=time.monotonic(): raise WorkspaceError('Edit expired or already used.')
            original=self._read(edit['path'])
            if (sha(original) if original is not None else None)!=edit['expected']: raise WorkspaceError('File changed; edit was not applied.')
            parts=self.parts(edit['path']);self.make_directories('/'.join(parts[:-1])); temp='.web-bridge-'+secrets.token_hex(12);recovery=None
            with self.parent(parts[:-1]) as (directory,parent):
                try:
                    fd=os.open(temp if directory is not None else parent/temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_BINARY',0),0o600,dir_fd=directory)
                    with os.fdopen(fd,'wb') as stream:
                        stream.write(edit['text'].encode());stream.flush();os.fsync(stream.fileno())
                    current=self._read_at(directory,parent,parts[-1])
                    if (sha(current) if current is not None else None)!=edit['expected']:raise WorkspaceError('File changed during edit; competing contents were preserved.')
                    if original is None:
                        try:os.link(temp if directory is not None else parent/temp,parts[-1] if directory is not None else parent/parts[-1],src_dir_fd=directory,dst_dir_fd=directory,follow_symlinks=False)
                        except FileExistsError:raise WorkspaceError('File was created concurrently; competing contents were preserved.') from None
                    else:recovery=self._publish_existing(directory,parent,parts[-1],temp,edit['expected'])
                finally:
                    try: os.unlink(temp if directory is not None else parent/temp,dir_fd=directory)
                    except FileNotFoundError: pass
            result={'applied':True,'path':edit['path'],'sha256':sha(edit['text'].encode())}
            if recovery:result['recovery_path']=recovery
            return result

    def snapshot(self,destination):
        dest=Path(destination)
        if dest.exists() or dest==self.root or self.root in dest.parents: raise WorkspaceError('Snapshot destination must be fresh and outside the workspace.')
        dest.mkdir(parents=True,mode=0o700);hashes={};modes={};omissions=[];total=0
        for name in self.walk(omissions):
            data=self._read(name)
            if data is None: raise WorkspaceError('Workspace changed while preparing snapshot.')
            total+=len(data)
            if total>50_000_000: raise WorkspaceError('Snapshot exceeds the 50 MB limit.')
            target=dest.joinpath(*name.split('/'));target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(data);hashes[name]=sha(data);modes[name]=self.root.joinpath(*name.split('/')).stat().st_mode
        return {'files':len(hashes),'bytes':total,'hashes':hashes,'modes':modes,'exclusions':list(EXCLUDED),'omitted_count':len(omissions),'omitted_paths':omissions[:100]}
