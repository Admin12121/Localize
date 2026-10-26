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
