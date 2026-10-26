import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from task_store import TaskStore, TaskStoreError


WS = {'workspace_id': 'selected-project', 'root': '/project', 'revision': 'abc123'}


def test_tasks_checkpoint_survives_restart_without_replaying_work(tmp_path):
    store = TaskStore(tmp_path)
    task = store.create('Create an artifact', ['file exists'], WS)
    store.claim(task['task_id'], 'agent', 30)
    store.checkpoint(task['task_id'], owner='agent', status='running',
                     evidence=[{'job_id': 'possibly-executed'}], handoff='Inspect job before continuing')
    store.close()
    reopened = TaskStore(tmp_path)
    saved = reopened.read(task['task_id'])
    assert saved['intent'] == 'Create an artifact'
    assert saved['checks'] == ['file exists']
    assert saved['status'] == 'partial'
    assert saved['evidence'] == [{'job_id': 'possibly-executed'}]
    assert 'Inspect job' in saved['handoff']
    assert len(saved['checkpoints']) >= 1
    assert reopened.list()[0]['task_id'] == task['task_id']
    reopened.close()


def test_task_lease_is_atomic_between_connections_and_only_owner_releases(tmp_path):
    a = TaskStore(tmp_path)
    b = TaskStore(tmp_path)
    task = a.create('Work', [], WS)
    a.claim(task['task_id'], 'writer-a', 1)
    with pytest.raises(TaskStoreError, match='lease'):
        b.claim(task['task_id'], 'writer-b', 1)
    with pytest.raises(TaskStoreError, match='lease'):
        b.checkpoint(task['task_id'], detail='competing writer')
    assert b.release(task['task_id'], 'writer-b') is False
    assert a.release(task['task_id'], 'writer-a') is True
    assert b.claim(task['task_id'], 'writer-b', 1)['lease']['owner'] == 'writer-b'
    b.close()
    a.close()


def test_workspace_mutation_lease_covers_revision_and_expiry(tmp_path):
    store = TaskStore(tmp_path)
    store.claim_workspace(WS, 'agent', .03)
    with pytest.raises(TaskStoreError, match='lease'):
        store.claim_workspace({**WS, 'revision': 'new'}, 'chat', 1)
    assert not store.release_workspace(WS, 'chat')
    time.sleep(.04)
    assert store.claim_workspace(WS, 'chat', 1)['owner'] == 'chat'
    store.invalidate_workspace(WS)
    assert store.claim_workspace(WS, 'next', 1)['owner'] == 'next'
    store.close()


def test_revision_checks_cancellation_and_bounds(tmp_path):
    store = TaskStore(tmp_path)
    task = store.create('Work', [], WS)
    current = store.checkpoint(task['task_id'], detail='saved', expected_revision=task['revision'])
    assert current['revision'] > task['revision']
    with pytest.raises(TaskStoreError, match='revision'):
        store.checkpoint(task['task_id'], detail='stale', expected_revision=task['revision'])
    assert store.cancel(task['task_id'])['status'] == 'cancelled'
    with pytest.raises(TaskStoreError):
        store.claim(task['task_id'], 'agent', 30)
    for intent, checks, workspace in [('', [], WS), ('x' * 16001, [], WS), ('ok', 'not-list', WS), ('ok', [], {})]:
        with pytest.raises(TaskStoreError):
            store.create(intent, checks, workspace)
    with pytest.raises(TaskStoreError):
        store.checkpoint(task['task_id'], status='invented')
    store.close()


def test_expired_running_task_requires_fresh_claim(tmp_path):
    store = TaskStore(tmp_path)
    task = store.create('Work', [], WS)
    store.claim(task['task_id'], 'old-agent', .02)
    store.checkpoint(task['task_id'], owner='old-agent', status='running')
    time.sleep(.03)
    assert store.read(task['task_id'])['status'] == 'partial'
    assert store.claim(task['task_id'], 'new-agent', 1)['lease']['owner'] == 'new-agent'
    store.close()


def test_operation_reservation_is_durable_and_never_replayed(tmp_path):
    store = TaskStore(tmp_path)
    task = store.create('Work', [], WS)
    store.claim(task['task_id'], 'agent', 30)
    assert store.reserve_operation(task['task_id'], 'a' * 64, 'agent') is True
    assert store.reserve_operation(task['task_id'], 'a' * 64, 'agent') is False
    store.close()
    store = TaskStore(tmp_path)
    store.claim(task['task_id'], 'new-agent', 30)
    assert store.reserve_operation(task['task_id'], 'a' * 64, 'new-agent') is False
    store.close()


def test_local_rebind_requires_same_root_and_no_live_writer(tmp_path):
    store = TaskStore(tmp_path)
    task = store.create('Work', [], WS)
    store.claim(task['task_id'], 'agent', 30)
    with pytest.raises(TaskStoreError):
        store.rebind(task['task_id'], {**WS, 'workspace_id': 'new-session'})
    store.release(task['task_id'], 'agent')
    with pytest.raises(TaskStoreError):
        store.rebind(task['task_id'], {**WS, 'root': '/another'})
    rebound = store.rebind(task['task_id'], {**WS, 'workspace_id': 'new-session', 'revision': 'new-revision'})
    assert rebound['status'] == 'partial'
    assert rebound['workspace']['revision'] == 'new-revision'
    store.close()


def test_releasing_active_writer_never_leaves_unowned_running_task(tmp_path):
    store = TaskStore(tmp_path)
    task = store.create('Work', [], WS)
    store.claim(task['task_id'], 'agent', 30)
    store.checkpoint(task['task_id'], owner='agent', status='running')
    store.release(task['task_id'], 'agent')
    assert store.read(task['task_id'])['status'] == 'partial'
    store.close()


def test_renewal_cannot_resurrect_invalidated_or_expired_lease(tmp_path):
    store = TaskStore(tmp_path)
    task = store.create('Work', [], WS)
    store.claim(task['task_id'], 'agent', 1)
    assert not store.renew(task['task_id'], 'another', 1)
    assert store.renew(task['task_id'], 'agent', 1)
    store.claim_workspace(WS, 'agent', 1)
    assert store.renew_workspace(WS, 'agent', 1)
    store.invalidate_workspace(WS)
    assert not store.renew_workspace(WS, 'agent', 1)
    assert store.claim_workspace(WS, 'chat', .02)
    time.sleep(.03)
    assert not store.renew_workspace(WS, 'chat', 1)
    store.release(task['task_id'], 'agent')
    assert not store.renew(task['task_id'], 'agent', 1)
    store.close()


def test_task_dashboard_uses_compact_summary_without_reading_large_document(tmp_path):
    import sqlite3,json
    store=TaskStore(tmp_path);task=store.create('Intent',['proof'],WS)
    store.checkpoint(task['task_id'],handoff='h'*8000,evidence=[{'large':'x'*30000}])
    def authorize(action,table,column,*unused):
        if action==sqlite3.SQLITE_READ and table=='tasks' and column=='document':return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    try:
        store.db.set_authorizer(authorize)
        summaries=store.summaries(WS)
        assert summaries[0]['task_id']==task['task_id']
        assert len(json.dumps(summaries))<2000
    finally:store.db.set_authorizer(None);store.close()

def test_dead_runner_process_lease_does_not_block_local_resume(tmp_path):
    import subprocess,json
    runtime=tmp_path/'runtime'
    script="import sys,json,os;sys.path.insert(0,sys.argv[1]);from task_store import TaskStore;s=TaskStore(sys.argv[2]);w=json.loads(sys.argv[3]);t=s.create('orphan',['inspect'],w);s.claim(t['task_id'],'dead-runner',3600);s.claim_workspace(w,'dead-runner',3600);s.checkpoint(t['task_id'],owner='dead-runner',status='running');print(t['task_id'],flush=True);os._exit(0)"
    completed=subprocess.run([sys.executable,'-c',script,str(Path(__file__).resolve().parents[1]/'server'),str(runtime),json.dumps(WS)],capture_output=True,text=True,timeout=10)
    assert completed.returncode==0,completed.stderr
    store=TaskStore(runtime)
    try:
        saved=store.read(completed.stdout.strip())
        assert saved['status']=='partial' and saved['lease'] is None
        assert store.claim_workspace(WS,'new-owner',60)['owner']=='new-owner'
        store.rebind(saved['task_id'],{**WS,'workspace_id':'fresh-session'})
    finally:store.close()
