import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from workspace import Workspace,WorkspaceError,sha
from file_operations import FileOperations

def setup(tmp_path):
    root=tmp_path/'project';root.mkdir()
    return root,Workspace(root),tmp_path/'runtime'

def test_nested_text_create_waits_for_approval_then_creates_parents(tmp_path):
    root,ws,_=setup(tmp_path)
    proposal=ws.propose('new/deep/proof.txt','written',None)
    assert not (root/'new').exists()
    ws.apply(proposal['edit_id'])
    assert (root/'new/deep/proof.txt').read_text()=='written'

def test_create_move_delete_and_restore_are_real_and_recoverable(tmp_path):
    root,ws,runtime=setup(tmp_path);ops=FileOperations(ws,runtime)
    mkdir=ops.propose('mkdir','new/deep')
    assert not (root/'new').exists()
    ops.apply(mkdir['edit_id']);assert (root/'new/deep').is_dir()
    (root/'a.txt').write_text('original')
    move=ops.propose('move','a.txt',destination='new/a.txt',expected_sha256=sha(b'original'))
    ops.apply(move['edit_id']);assert not (root/'a.txt').exists()
    delete=ops.propose('delete','new/a.txt',expected_sha256=sha(b'original'))
    result=ops.apply(delete['edit_id'])
    assert not (root/'new/a.txt').exists()
    restore=ops.propose('restore','new/a.txt',trash_id=result['trash_id'])
    ops.apply(restore['edit_id'])
    assert (root/'new/a.txt').read_text()=='original'

def test_competing_change_is_never_deleted(tmp_path):
    root,ws,runtime=setup(tmp_path);ops=FileOperations(ws,runtime)
    (root/'a.txt').write_text('before')
    delete=ops.propose('delete','a.txt',expected_sha256=sha(b'before'))
    (root/'a.txt').write_text('after')
    with pytest.raises(WorkspaceError):ops.apply(delete['edit_id'])
    assert (root/'a.txt').read_text()=='after'


def test_source_change_at_rename_boundary_is_preserved_and_denied(tmp_path,monkeypatch):
    root,ws,runtime=setup(tmp_path);ops=FileOperations(ws,runtime)
    (root/'a.txt').write_text('approved')
    proposal=ops.propose('move','a.txt',destination='new/a.txt',expected_sha256=sha(b'approved'))
    original=ops._rename
    def race(*args,**kwargs):
        (root/'a.txt').write_text('concurrent')
        return original(*args,**kwargs)
    monkeypatch.setattr(ops,'_rename',race)
    with pytest.raises(WorkspaceError,match='changed'):
        ops.apply(proposal['edit_id'])
    assert (root/'a.txt').read_text()=='concurrent'
    assert not (root/'new/a.txt').exists()


def test_destination_created_at_native_rename_boundary_is_never_overwritten(tmp_path,monkeypatch):
    root,ws,runtime=setup(tmp_path);ops=FileOperations(ws,runtime)
    (root/'a.txt').write_text('approved')
    proposal=ops.propose('move','a.txt',destination='target.txt',expected_sha256=sha(b'approved'))
    original=ops._native_rename
    def race(*args,**kwargs):
        (root/'target.txt').write_text('concurrent')
        return original(*args,**kwargs)
    monkeypatch.setattr(ops,'_native_rename',race)
    with pytest.raises(WorkspaceError):ops.apply(proposal['edit_id'])
    assert (root/'a.txt').read_text()=='approved'
    assert (root/'target.txt').read_text()=='concurrent'


def test_recursive_directory_delete_and_restore_preserve_tree(tmp_path):
    root,ws,runtime=setup(tmp_path);ops=FileOperations(ws,runtime)
    (root/'folder/deep').mkdir(parents=True);(root/'folder/deep/a.txt').write_text('original')
    result=ops.apply(ops.propose('delete','folder',recursive=True)['edit_id'])
    assert not (root/'folder').exists()
    restore=ops.propose('restore','folder',trash_id=result['trash_id'])
    ops.apply(restore['edit_id'])
    assert (root/'folder/deep/a.txt').read_text()=='original'


def test_directory_edit_during_native_move_is_rolled_back_without_content_loss(tmp_path,monkeypatch):
    root,ws,runtime=setup(tmp_path);ops=FileOperations(ws,runtime)
    (root/'folder').mkdir();(root/'folder/a.txt').write_text('approved')
    proposal=ops.propose('move','folder',destination='target')
    original=ops._native_rename
    first=True
    def race(*args,**kwargs):
        nonlocal first
        if first:
            first=False;(root/'folder/a.txt').write_text('concurrent')
        return original(*args,**kwargs)
    monkeypatch.setattr(ops,'_native_rename',race)
    with pytest.raises(WorkspaceError,match='changed'):
        ops.apply(proposal['edit_id'])
    assert (root/'folder/a.txt').read_text()=='concurrent'
    assert not (root/'target').exists()


def test_failed_delete_rollback_retains_recovery_record_and_both_versions(tmp_path,monkeypatch):
    import json
    root,ws,runtime=setup(tmp_path);ops=FileOperations(ws,runtime)
    (root/'folder').mkdir();(root/'folder/a.txt').write_text('approved')
    proposal=ops.propose('delete','folder',recursive=True)
    original=ops._native_rename
    first=True
    def race(source,destination,*args,**kwargs):
        nonlocal first
        result=original(source,destination,*args,**kwargs)
        if first:
            first=False
            (root/destination/'a.txt').write_text('concurrent-existing-handle')
            (root/'folder').mkdir();(root/'folder/new.txt').write_text('new-original-path')
        return result
    monkeypatch.setattr(ops,'_native_rename',race)
    with pytest.raises(WorkspaceError):ops.apply(proposal['edit_id'])
    records=list(runtime.glob('*.json'))
    assert len(records)==1, 'A failed rollback must retain its durable recovery record'
    record=json.loads(records[0].read_text())
    assert (root/'folder/new.txt').read_text()=='new-original-path'
    assert (root/record['tag']/'a.txt').read_text()=='concurrent-existing-handle'
    (root/'folder').rename(root/'new-version')
    restored=ops.propose('restore','folder',trash_id=records[0].stem)
    ops.apply(restored['edit_id'])
    assert (root/'folder/a.txt').read_text()=='concurrent-existing-handle'


@pytest.mark.skipif(sys.platform!='win32',reason='Windows sharing enforcement')
def test_existing_windows_writer_prevents_source_mutation(tmp_path):
    root,ws,runtime=setup(tmp_path);ops=FileOperations(ws,runtime)
    (root/'a.txt').write_text('approved')
    proposal=ops.propose('move','a.txt',destination='target.txt',expected_sha256=sha(b'approved'))
    with (root/'a.txt').open('r+'):
        with pytest.raises(WorkspaceError,match='edited|unavailable'):
            ops.apply(proposal['edit_id'])
    assert (root/'a.txt').read_text()=='approved'
    assert not (root/'target.txt').exists()

def test_recursive_removal_requires_explicit_flag_and_rejects_exclusions(tmp_path):
    root,ws,runtime=setup(tmp_path);ops=FileOperations(ws,runtime)
    (root/'folder').mkdir();(root/'folder/a.txt').write_text('a')
    with pytest.raises(WorkspaceError):ops.propose('delete','folder')
    proposal=ops.propose('delete','folder',recursive=True)
    (root/'folder/.env').write_text('secret')
    with pytest.raises(WorkspaceError):ops.apply(proposal['edit_id'])
    assert (root/'folder/a.txt').exists()

@pytest.mark.parametrize('path',['../outside','/absolute','.git/config','x/../../outside'])
def test_mutations_reject_unsafe_paths(tmp_path,path):
    _,ws,runtime=setup(tmp_path);ops=FileOperations(ws,runtime)
    with pytest.raises(WorkspaceError):ops.propose('mkdir',path)


def test_recursive_preview_lists_bounded_affected_paths(tmp_path):
    root,ws,runtime=setup(tmp_path);ops=FileOperations(ws,runtime)
    (root/'folder').mkdir()
    for index in range(230):(root/'folder'/('file%03d.txt'%index)).write_text('x')
    item=ops.propose('delete','folder',recursive=True)
    preview=ops.preview(item['edit_id'])
    assert preview['affected_count']==231
    assert preview['truncated'] is True
    assert len(preview['affected_paths'])<=200
    assert 'folder/file000.txt' in preview['diff']
    assert (root/'folder/file229.txt').exists()
