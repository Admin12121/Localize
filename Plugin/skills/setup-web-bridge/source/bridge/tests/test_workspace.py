import hashlib
import os
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from workspace import Workspace, WorkspaceError

def digest(text): return hashlib.sha256(text.encode()).hexdigest()

def test_workspace_paths_exclusions_and_regular_files(tmp_path):
    (tmp_path/'main.py').write_text('print(1)', encoding='utf-8')
    (tmp_path/'.env').write_text('secret')
    ws=Workspace(tmp_path,'demo')
    assert ws.read('main.py')['text']=='print(1)'
    assert [x['path'] for x in ws.listing()['entries']]==['main.py']
    for path in ['../secret','/etc/passwd','C:/Windows/x','\\\\host\\share','x:stream','CON','a/NUL.txt','.env','.git/config','node_modules/a','a/../main.py']:
        with pytest.raises(WorkspaceError): ws.read(path)

def test_edits_are_proposals_then_atomic_hash_checked_changes(tmp_path):
    p=tmp_path/'main.txt'; p.write_bytes(b'before\n')
    ws=Workspace(tmp_path,'demo')
    proposal=ws.propose('main.txt','after\n',digest('before\n'))
    assert '-before' in proposal['diff'] and '+after' in proposal['diff']
    assert p.read_text()=='before\n'
    ws.apply(proposal['edit_id'])
    assert p.read_text()=='after\n'
    with pytest.raises(WorkspaceError): ws.apply(proposal['edit_id'])
    proposal=ws.propose('main.txt','replacement',digest('after\n'))
    p.write_text('user concurrent edit')
    with pytest.raises(WorkspaceError,match='changed'): ws.apply(proposal['edit_id'])

def test_filtered_snapshot_never_copies_sensitive_files_or_links(tmp_path):
    root=tmp_path/'repo';root.mkdir();(root/'app.py').write_text('safe')
    (root/'.env.local').write_text('private');(root/'.git').mkdir();(root/'.git'/'config').write_text('private')
    ws=Workspace(root,'demo');dest=tmp_path/'snapshot';info=ws.snapshot(dest)
    assert (dest/'app.py').read_text()=='safe'
    assert not (dest/'.env.local').exists() and not (dest/'.git').exists()
    assert info['files']==1
    try: (root/'linked').symlink_to(tmp_path, target_is_directory=True)
    except OSError: return
    with pytest.raises(WorkspaceError): ws.read('linked/repo/app.py')
    assert all(x['path']!='linked' for x in ws.listing()['entries'])

def test_search_is_bounded_and_new_file_creation_uses_absent_hash(tmp_path):
    (tmp_path/'a.txt').write_text('needle\nother\nneedle')
    ws=Workspace(tmp_path,'demo')
    assert len(ws.search('needle')['matches'])==2
    proposal=ws.propose('new.txt','new',None); ws.apply(proposal['edit_id'])
    assert (tmp_path/'new.txt').read_text()=='new'
    with pytest.raises(WorkspaceError): ws.propose('new.txt','oops',None)

@pytest.mark.skipif(os.name!='nt',reason='Windows 8.3 alias regression')
def test_windows_short_names_cannot_bypass_exclusions(tmp_path):
    import ctypes
    from ctypes import wintypes
    repo=tmp_path/'project';repo.mkdir();(repo/'.git').mkdir();(repo/'.git'/'HEAD').write_text('private metadata')
    (repo/'.env.private').write_text('secret')
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.GetShortPathNameW.argtypes=[wintypes.LPCWSTR,wintypes.LPWSTR,wintypes.DWORD]
    checked=0
    ws=Workspace(repo)
    root_buffer=ctypes.create_unicode_buffer(32768)
    assert api.GetShortPathNameW(str(repo),root_buffer,len(root_buffer))
    for relative in ['.git/HEAD','.env.private']:
        buffer=ctypes.create_unicode_buffer(32768)
        assert api.GetShortPathNameW(str(repo/relative),buffer,len(buffer))
        alias=Path(buffer.value).relative_to(Path(root_buffer.value)).as_posix()
        if alias.casefold()==relative.casefold():continue
        checked+=1
        with pytest.raises(WorkspaceError):ws.read(alias)
        with pytest.raises(WorkspaceError):ws.propose(alias,'replacement',None)
    if not checked:pytest.skip('8.3 short names disabled on this volume')

def test_large_files_and_linked_paths_are_rejected(tmp_path):
    root=tmp_path/'project';root.mkdir();(root/'large.txt').write_bytes(b'x'*256001)
    ws=Workspace(root)
    with pytest.raises(WorkspaceError):ws.read('large.txt')
    outside=tmp_path/'outside';outside.mkdir();(outside/'secret.txt').write_text('secret')
    link=root/'linked'
    if os.name=='nt':
        import subprocess
        result=subprocess.run(['cmd.exe','/c','mklink','/J',str(link),str(outside)],capture_output=True)
        if result.returncode:pytest.skip('Junction creation unavailable')
    else:link.symlink_to(outside,target_is_directory=True)
    with pytest.raises(WorkspaceError):ws.read('linked/secret.txt')

def test_hard_links_and_rebound_root_are_rejected(tmp_path):
    root=tmp_path/'parent'/'project';root.mkdir(parents=True)
    outside=tmp_path/'private.txt';outside.write_text('private')
    os.link(outside,root/'innocent.txt');ws=Workspace(root)
    with pytest.raises(WorkspaceError):ws.read('innocent.txt')
    with pytest.raises(WorkspaceError):ws.snapshot(tmp_path/'stage')
    (root/'safe.txt').write_text('approved')
    root.parent.rename(tmp_path/'original-parent')
    root.mkdir(parents=True);(root/'safe.txt').write_text('rebound')
    with pytest.raises(WorkspaceError):ws.read('safe.txt')

@pytest.mark.parametrize('existing',[True,False])
def test_concurrent_save_during_edit_commit_is_preserved(tmp_path,monkeypatch,existing):
    import workspace
    path=tmp_path/'main.txt'
    if existing:path.write_bytes(b'original')
    ws=Workspace(tmp_path);edit=ws.propose('main.txt','bridge change',digest('original') if existing else None)
    original_fsync=workspace.os.fsync
    def race(fd):
        original_fsync(fd);path.write_bytes(b'competing editor change')
    monkeypatch.setattr(workspace.os,'fsync',race)
    with pytest.raises(WorkspaceError):ws.apply(edit['edit_id'])
    assert path.read_bytes()==b'competing editor change'
