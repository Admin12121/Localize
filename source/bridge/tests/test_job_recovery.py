"""Durable receipts survive owner restart without replay."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import pytest
SERVER = Path(__file__).resolve().parents[1] / 'server'
sys.path.insert(0, str(SERVER))
from jobs import Jobs
from workspace import Workspace, WorkspaceError

def ready(tmp_path):
    root=tmp_path/'repo';root.mkdir(exist_ok=True)
    return Jobs(tmp_path/'runtime',threading.RLock(),lambda generation:generation==1),Workspace(root)

def request(jobs,workspace,code='print("receipt-proof")',key='durable-key-001',**options):
    return jobs.request([sys.executable,'-c',code],'',10,'host',key,workspace,1,False,'python:3.12-alpine',**options)

def finish(jobs,result):
    jobs.approve(result['job_id'],True)
    assert jobs.items[result['job_id']]['settled'].wait(10)
    return jobs.status(result['job_id'])

def test_pending_receipt_is_recovered_without_launch_or_reapproval(tmp_path):
    jobs,ws=ready(tmp_path)
    code='from pathlib import Path;Path("unexpected").write_text("ran")'
    queued=request(jobs,ws,code)
    restarted=Jobs(jobs.runtime,threading.RLock(),lambda generation:True)
    recovered=restarted.status(queued['job_id'])
    assert recovered['state']=='interrupted'
    assert recovered['outcome_unknown'] is True
    assert recovered['previous_state']=='pending'
    assert recovered['recovery_required'] is False
    assert restarted.unresolved(ws)==[]
    assert 'review' in recovered['recovery_note'].lower()
    assert recovered['session_id']!=restarted.session_id
    assert not restarted.items
    with pytest.raises(WorkspaceError):restarted.approve(queued['job_id'],True)
    with pytest.raises(WorkspaceError):request(restarted,ws,code)
    assert not (ws.root/'unexpected').exists()

def test_key_binds_workspace_and_write_policy_before_any_side_effect(tmp_path):
    jobs,ws=ready(tmp_path)
    queued=request(jobs,ws)
    assert request(jobs,ws)['job_id']==queued['job_id']
    other=tmp_path/'other';other.mkdir()
    with pytest.raises(WorkspaceError):request(jobs,Workspace(other))
    with pytest.raises(WorkspaceError):request(jobs,ws,write=True)
    with pytest.raises(WorkspaceError):request(jobs,ws,'print("changed")')
    assert len(jobs.items)==1

def test_completed_receipt_survives_restart_with_identity_and_cursor(tmp_path):
    jobs,ws=ready(tmp_path)
    code='from pathlib import Path;Path("runs").write_text("once");print("abcdef")'
    completed=finish(jobs,request(jobs,ws,code))
    restarted=Jobs(jobs.runtime,threading.RLock(),lambda generation:True)
    recovered=restarted.status(completed['job_id'],3)
    assert recovered['state']=='completed'
    assert recovered['output'].startswith('def')
    assert recovered['next_output_offset']==len(completed['output'])
    assert recovered['execution']['pid']>0
    assert recovered['execution']['environment']=='host'
    assert recovered['exit_code']==0
    assert recovered['submitted_at']<=recovered['started_at']<=recovered['finished_at']
    assert recovered['cleanup_pending'] is False
    assert recovered['session_id']==completed['session_id']
    assert recovered['request']['argv']==completed['request']['argv']
    with pytest.raises(WorkspaceError):request(restarted,ws,code)
    assert (ws.root/'runs').read_text()=='once'
    assert restarted.summaries()[0]['job_id']==completed['job_id']

def test_abrupt_owner_exit_preserves_running_execution_identity(tmp_path):
    root=tmp_path/'repo';root.mkdir()
    runtime=tmp_path/'runtime';identity=tmp_path/'identity.json'
    script="""
import json,os,sys,threading,time
from pathlib import Path
from jobs import Jobs
from workspace import Workspace
jobs=Jobs(sys.argv[1],threading.RLock(),lambda generation:True)
job=jobs.request([sys.executable,'-c','import time;time.sleep(2)'],'',10,'host','crashed-running-01',Workspace(sys.argv[2]),1,False,'python:3.12-alpine')
jobs.approve(job['job_id'],True)
deadline=time.monotonic()+8
while time.monotonic()<deadline:
    current=jobs.status(job['job_id'])
    if current['state']=='running':
        Path(sys.argv[3]).write_text(json.dumps(current))
        os._exit(0)
    time.sleep(.01)
raise RuntimeError('command never started')
"""
    env=dict(os.environ,PYTHONPATH=str(SERVER))
    child=subprocess.run([sys.executable,'-c',script,str(runtime),str(root),str(identity)],env=env,capture_output=True,timeout=15)
    assert child.returncode==0,child.stderr.decode()
    lost=json.loads(identity.read_text())
    restarted=Jobs(runtime,threading.RLock(),lambda generation:True)
    recovered=restarted.status(lost['job_id'])
    assert recovered['state']=='interrupted'
    assert recovered['previous_state']=='running'
    workspace=Workspace(root)
    blockers=restarted.unresolved(workspace)
    assert [item['job_id'] for item in blockers]==[lost['job_id']]
    assert blockers[0]['execution']['pid']==lost['execution']['pid']
    other=tmp_path/'other';other.mkdir()
    assert restarted.unresolved(Workspace(other))==[]
    with pytest.raises(WorkspaceError):restarted.acknowledge_recovery(lost['job_id'],Workspace(other))
    with pytest.raises(WorkspaceError):restarted.acknowledge_recovery(lost['job_id'],Workspace(other),allow_unbound=True)
    assert restarted.unresolved(workspace)
    acknowledged=restarted.acknowledge_recovery(lost['job_id'],workspace)
    assert acknowledged['state']=='interrupted'
    assert acknowledged['success'] is False
    assert acknowledged['recovery_required'] is False
    assert acknowledged['recovery_acknowledged']['confirmation']=='stopped/reviewed'
    assert restarted.unresolved(workspace)==[]
    again=Jobs(runtime,threading.RLock(),lambda generation:True)
    assert again.unresolved(workspace)==[]
    assert again.status(lost['job_id'])['recovery_acknowledged']==acknowledged['recovery_acknowledged']
    assert recovered['outcome_unknown'] is True
    assert recovered['execution']['pid']==lost['execution']['pid']
    assert recovered['execution']['started_at']==lost['started_at']
    assert recovered['cleanup_pending'] is False
    assert not restarted.items

def test_denied_and_cancelled_pending_receipts_are_terminal_after_restart(tmp_path):
    jobs,ws=ready(tmp_path)
    denied=request(jobs,ws);jobs.approve(denied['job_id'],False)
    cancelled=request(jobs,ws,key='durable-cancel-01');jobs.cancel(cancelled['job_id'])
    restarted=Jobs(jobs.runtime,threading.RLock(),lambda generation:True)
    assert restarted.status(denied['job_id'])['state']=='denied'
    assert restarted.status(cancelled['job_id'])['state']=='cancelled'
    assert restarted.status(cancelled['job_id'])['cleanup_pending'] is False

def test_output_is_bounded_on_disk_and_old_receipts_keep_tombstones(tmp_path):
    jobs,ws=ready(tmp_path)
    first=finish(jobs,request(jobs,ws,'print("x"*200000)'))
    assert len(first['output'])<=64000
    assert first['truncated'] is True
    for index in range(205):
        queued=request(jobs,ws,key='rotate-receipt-'+str(index))
        jobs.approve(queued['job_id'],False)
    restarted=Jobs(jobs.runtime,threading.RLock(),lambda generation:True)
    old=restarted.status(first['job_id'])
    assert old['history_archived'] is True
    assert old['output']==''
    assert len(restarted.summaries())<=200
    assert 'request' not in restarted.summaries()[0]
    assert 'output' not in restarted.summaries()[0]
    with pytest.raises(WorkspaceError):request(restarted,ws,'print("x"*200000)')
    assert not restarted.items

def test_approval_storage_failure_never_launches_or_leaks_authority(tmp_path):
    import sqlite3
    jobs,ws=ready(tmp_path)
    code='from pathlib import Path;Path("unauthorized").write_text("ran")'
    queued=request(jobs,ws,code)
    holders=set()
    jobs.on_approve=lambda key:holders.add(key)
    jobs.on_finish=lambda key:holders.discard(key)
    with sqlite3.connect(jobs.receipt_path) as db:
        db.execute("""CREATE TRIGGER reject_approval BEFORE UPDATE ON receipts
            WHEN json_extract(NEW.result,'$.state')='approved'
            BEGIN SELECT RAISE(FAIL,'fixture storage failure'); END""")
    with pytest.raises(WorkspaceError):jobs.approve(queued['job_id'],True)
    assert not holders
    assert jobs.status(queued['job_id'])['state']=='pending'
    assert not (ws.root/'unauthorized').exists()
    assert jobs.items[queued['job_id']]['process'] is None

def test_unsettled_terminal_receipt_recovers_as_unknown_without_losing_exit(tmp_path):
    import sqlite3
    jobs,ws=ready(tmp_path)
    completed=finish(jobs,request(jobs,ws,'import sys;print("exit-evidence");sys.exit(7)'))
    # Simulate lost confirmation of cleanup after persisting terminal evidence.
    with sqlite3.connect(jobs.receipt_path) as db:
        db.execute('UPDATE receipts SET settled=0 WHERE job_id=?',(completed['job_id'],))
    restarted=Jobs(jobs.runtime,threading.RLock(),lambda generation:True)
    recovered=restarted.status(completed['job_id'])
    assert recovered['state']=='interrupted'
    assert recovered['previous_state']=='failed'
    assert recovered['outcome_unknown'] is True
    assert recovered['exit_code']==7
    assert 'exit-evidence' in recovered['output']

def test_receipt_write_failure_does_not_prevent_owner_cancellation(tmp_path):
    import sqlite3
    jobs,ws=ready(tmp_path)
    queued=request(jobs,ws,'import time;time.sleep(60)')
    jobs.approve(queued['job_id'],True)
    deadline=time.monotonic()+5
    while jobs.status(queued['job_id'])['state']!='running' and time.monotonic()<deadline:time.sleep(.01)
    live=jobs.items[queued['job_id']]
    with sqlite3.connect(jobs.receipt_path) as db:
        db.execute("""CREATE TRIGGER reject_cancel_confirmation BEFORE UPDATE ON receipts
            WHEN json_extract(NEW.result,'$.state')='cancelled' AND NEW.settled=0
            BEGIN SELECT RAISE(FAIL,'fixture storage failure'); END""")
    try:
        with pytest.raises(WorkspaceError):jobs.cancel(queued['job_id'])
        assert live['settled'].wait(3)
        assert live['process'].poll() is not None
    finally:
        if live['group']:live['group'].kill()
        elif live['process'] and live['process'].poll() is None:live['process'].kill()
        live['settled'].wait(3)


def test_approved_receipt_blocks_launch_until_matching_owner_acknowledges(tmp_path):
    import sqlite3
    jobs,ws=ready(tmp_path)
    queued=request(jobs,ws)
    with sqlite3.connect(jobs.receipt_path) as db:
        raw=json.loads(db.execute('SELECT result FROM receipts WHERE job_id=?',(queued['job_id'],)).fetchone()[0])
        raw['state']='approved'
        db.execute('UPDATE receipts SET result=? WHERE job_id=?',(json.dumps(raw),queued['job_id']))
    restarted=Jobs(jobs.runtime,threading.RLock(),lambda generation:True)
    assert restarted.status(queued['job_id'])['recovery_required'] is True
    assert restarted.unresolved(ws)[0]['job_id']==queued['job_id']
    fresh=request(restarted,ws,'from pathlib import Path;Path("fresh").write_text("ran")',key='fresh-after-recovery')
    with pytest.raises(WorkspaceError):restarted.approve(fresh['job_id'],True)
    assert not (ws.root/'fresh').exists()
    with pytest.raises(WorkspaceError):restarted.acknowledge_recovery(fresh['job_id'],ws)
    restarted.acknowledge_recovery(queued['job_id'],ws)
    done=finish(restarted,fresh)
    assert done['state']=='completed'
    assert (ws.root/'fresh').read_text()=='ran'

def test_scope_migration_and_compaction_preserve_recovery_blocker(tmp_path):
    import hashlib
    import sqlite3
    jobs,ws=ready(tmp_path)
    queued=request(jobs,ws)
    expected=hashlib.sha256(os.path.normcase(str(ws.root)).encode()).hexdigest()
    assert queued['workspace_scope']==expected
    assert str(ws.root) not in json.dumps(queued)
    # Older receipt databases have neither scope nor recovery indexing columns.
    with sqlite3.connect(jobs.receipt_path) as db:
        raw=json.loads(db.execute('SELECT result FROM receipts WHERE job_id=?',(queued['job_id'],)).fetchone()[0])
        raw['state']='running';raw['execution']={'pid':123,'environment':'host'}
        db.execute('UPDATE receipts SET result=? WHERE job_id=?',(json.dumps(raw),queued['job_id']))
        db.execute('DROP INDEX IF EXISTS receipt_recovery_scope')
        db.execute('ALTER TABLE receipts DROP COLUMN workspace_scope')
        db.execute('ALTER TABLE receipts DROP COLUMN recovery_required')
    restarted=Jobs(jobs.runtime,threading.RLock(),lambda generation:True)
    assert restarted.unresolved(ws)[0]['job_id']==queued['job_id']
    for index in range(165):
        later=request(restarted,ws,key='scope-compaction-'+str(index))
        restarted.approve(later['job_id'],False)
    compacted=Jobs(jobs.runtime,threading.RLock(),lambda generation:True)
    old=compacted.status(queued['job_id'])
    assert old['workspace_scope']==expected
    assert old['history_archived'] is True
    assert old['outcome_unknown'] is True
    assert old['recovery_required'] is True
    assert compacted.unresolved(ws)[0]['job_id']==queued['job_id']
    compacted.acknowledge_recovery(queued['job_id'],ws)
    assert compacted.unresolved(ws)==[]


def test_legacy_unbound_execution_requires_explicit_local_migration_acknowledgement(tmp_path):
    import sqlite3
    jobs,ws=ready(tmp_path)
    queued=request(jobs,ws)
    with sqlite3.connect(jobs.receipt_path) as db:
        raw=json.loads(db.execute('SELECT result FROM receipts WHERE job_id=?',(queued['job_id'],)).fetchone()[0])
        raw.pop('workspace_scope',None)
        raw['state']='running';raw['execution']={'pid':123,'environment':'host'}
        db.execute('UPDATE receipts SET result=? WHERE job_id=?',(json.dumps(raw),queued['job_id']))
        if 'workspace_scope' in {row[1] for row in db.execute('PRAGMA table_info(receipts)')}:
            db.execute("UPDATE receipts SET workspace_scope='' WHERE job_id=?",(queued['job_id'],))
    restarted=Jobs(jobs.runtime,threading.RLock(),lambda generation:True)
    other=tmp_path/'other';other.mkdir()
    assert restarted.unresolved(ws)
    assert restarted.unresolved(Workspace(other))
    with pytest.raises(WorkspaceError):restarted.acknowledge_recovery(queued['job_id'],ws)
    with pytest.raises(WorkspaceError):restarted.acknowledge_recovery(queued['job_id'],ws,allow_unbound='yes')
    ack=restarted.acknowledge_recovery(queued['job_id'],ws,allow_unbound=True)
    assert ack['outcome_unknown'] is True
    assert ack['recovery_acknowledged']['legacy_unbound'] is True
    assert restarted.unresolved(ws)==[]
    assert restarted.unresolved(Workspace(other))==[]

def test_dashboard_reads_only_compact_receipts_and_preserves_human_shell_label(tmp_path,monkeypatch):
    import sqlite3
    jobs,ws=ready(tmp_path)
    first=finish(jobs,request(jobs,ws,'import sys;sys.stdout.write("x"*60000)',metadata={'command':'human readable command','shell':'sh'}))
    restarted=Jobs(jobs.runtime,threading.RLock(),lambda generation:True)
    connect=sqlite3.connect
    def summary_only(*args,**kwargs):
        db=connect(*args,**kwargs)
        # Enforce the dashboard read contract at the actual SQLite boundary.
        def authorize(action,table,column,*ignored):
            return sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_READ and table=='receipts' and column=='result' else sqlite3.SQLITE_OK
        db.set_authorizer(authorize)
        return db
    monkeypatch.setattr(sqlite3,'connect',summary_only)
    rows=restarted.summaries()
    assert rows[0]['job_id']==first['job_id']
    assert rows[0]['label']=='human readable command'
    assert rows[0]['output_length']==60000
    assert rows[0]['state']=='completed'
    assert 'output' not in rows[0]
    assert 'request' not in rows[0]
    assert len(json.dumps(rows))<1000

class LocalExecutionProject:
    """Model a Docker CLI and its independent workload with two real processes."""
    def __init__(self,root,fail_cancel=False):
        self.root=root;self.fail_cancel=fail_cancel;self._jobs={};self.worker=None
    def validate_workspace(self,workspace):workspace.check_root()
    def build_command(self,key,argv,cwd):
        code='import time;from pathlib import Path;time.sleep(.75);Path('+repr(str(self.root/'orphan-mutated'))+').write_text("mutated");time.sleep(60)'
        options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
        self.worker=subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**options)
        self._jobs[key]={'container_id':'fixture-container','context':'fixture-context','token':'private-cancellation-token','worker':self.worker}
        return [sys.executable,'-c','import time;print("independent-workload-started",flush=True);time.sleep(60)']
    def cancel(self,key):
        if self.fail_cancel:raise WorkspaceError('Fixture engine unavailable; cancellation unconfirmed.')
        if key not in self._jobs:return False
        self.worker.kill();self.worker.wait(timeout=5);self._jobs.pop(key)
        return True
    def finish(self,key):return self._jobs.pop(key,None) is not None
    def cleanup(self):
        if self.worker and self.worker.poll() is None:self.worker.kill();self.worker.wait(timeout=5)

@pytest.mark.parametrize('after_output',[False,True])
def test_storage_failure_cancels_owned_workload_before_releasing_lease(tmp_path,after_output):
    import sqlite3
    jobs,ws=ready(tmp_path);project=LocalExecutionProject(ws.root);jobs.project=project
    holders=set();released_while_live=[]
    jobs.on_approve=lambda key:holders.add(key)
    def release(key):
        released_while_live.append(project.worker.poll() is None);holders.discard(key)
    jobs.on_finish=release
    queued=jobs.request(['fixture-command'],'',10,'docker','docker-write-failure',ws,1,False,'unused')
    with sqlite3.connect(jobs.receipt_path) as db:
        predicate=" AND json_extract(NEW.result,'$.output')<>''" if after_output else ''
        db.execute("CREATE TRIGGER reject_running_receipt BEFORE UPDATE ON receipts WHEN json_extract(NEW.result,'$.state')='running'"+predicate+" BEGIN SELECT RAISE(FAIL,'fixture storage failure'); END")
    try:
        jobs.approve(queued['job_id'],True)
        assert jobs.items[queued['job_id']]['settled'].wait(5)
        assert project.worker.poll() is not None
        assert queued['job_id'] not in project._jobs
        assert not holders
        assert released_while_live==[False]
        time.sleep(.85)
        assert not (ws.root/'orphan-mutated').exists()
    finally:project.cleanup()

def test_failed_docker_cleanup_retains_identity_and_memory_blocker_during_storage_failure(tmp_path):
    import sqlite3
    jobs,ws=ready(tmp_path);project=LocalExecutionProject(ws.root,fail_cancel=True);jobs.project=project
    holders=set();jobs.on_approve=lambda key:holders.add(key);jobs.on_finish=lambda key:holders.discard(key)
    queued=jobs.request(['fixture-command'],'',10,'docker','docker-cleanup-unknown',ws,1,False,'unused')
    with sqlite3.connect(jobs.receipt_path) as db:
        db.execute("""CREATE TRIGGER reject_execution_receipts BEFORE UPDATE ON receipts
            WHEN (json_extract(NEW.result,'$.state')='running' AND json_extract(NEW.result,'$.output')<>'')
              OR json_extract(NEW.result,'$.state') IN ('failed','interrupted')
            BEGIN SELECT RAISE(FAIL,'fixture storage failure'); END""")
    try:
        jobs.approve(queued['job_id'],True)
        assert jobs.items[queued['job_id']]['settled'].wait(5)
        result=jobs.status(queued['job_id'])
        assert result['state']=='interrupted'
        assert result['outcome_unknown'] is True
        assert result['recovery_required'] is True
        assert queued['job_id'] in project._jobs
        assert project.worker.poll() is None
        assert holders=={queued['job_id']}
        # Recovery blocking survives unavailable storage in the current process.
        with sqlite3.connect(jobs.receipt_path) as db:
            db.execute('DROP TRIGGER reject_execution_receipts')
        original_database=jobs.database
        from contextlib import contextmanager
        @contextmanager
        def unavailable():raise WorkspaceError('Fixture storage unavailable.');yield
        jobs.database=unavailable
        try:assert jobs.unresolved(ws)[0]['job_id']==queued['job_id']
        finally:jobs.database=original_database
        fresh=request(jobs,ws,key='after-failed-cleanup')
        with pytest.raises(WorkspaceError):jobs.approve(fresh['job_id'],True)
        project.cleanup()
        ack=jobs.acknowledge_recovery(queued['job_id'],ws)
        assert ack['recovery_required'] is False
        assert not holders
        assert queued['job_id'] not in project._jobs
        assert jobs.unresolved(ws)==[]
    finally:project.cleanup()

def test_owner_cancel_failure_still_stops_cli_and_keeps_workload_recovery_authority(tmp_path):
    jobs,ws=ready(tmp_path);project=LocalExecutionProject(ws.root,fail_cancel=True);jobs.project=project
    holders=set();jobs.on_approve=lambda key:holders.add(key);jobs.on_finish=lambda key:holders.discard(key)
    queued=jobs.request(['fixture-command'],'',10,'docker','docker-owner-cancel-fail',ws,1,False,'unused')
    try:
        jobs.approve(queued['job_id'],True)
        deadline=time.monotonic()+5
        while jobs.status(queued['job_id'])['state']!='running' and time.monotonic()<deadline:time.sleep(.01)
        with pytest.raises(WorkspaceError):jobs.cancel(queued['job_id'])
        live=jobs.items[queued['job_id']]
        assert live['settled'].wait(5)
        assert live['process'].poll() is not None
        assert project.worker.poll() is None
        assert queued['job_id'] in project._jobs
        assert holders=={queued['job_id']}
        assert jobs.status(queued['job_id'])['recovery_required'] is True
        assert jobs.unresolved(ws)[0]['job_id']==queued['job_id']
        restarted=Jobs(jobs.runtime,threading.RLock(),lambda generation:True)
        assert restarted.unresolved(ws)[0]['job_id']==queued['job_id']
    finally:project.cleanup()
