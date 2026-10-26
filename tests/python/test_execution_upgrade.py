import sys
import time
from pathlib import Path
import pytest
from web_bridge.app import Companion
from web_bridge.workspace.files import WorkspaceError

def fixture(tmp_path):
    root=tmp_path/'project';root.mkdir()
    c=Companion(None,tmp_path/'runtime')
    c.configure(root=str(root),read=True,write=True,execution=True,host=True)
    return c,root

def finish(c,argv,timeout=5):
    job=c.command_request(argv,idempotency_key='test-'+str(time.time_ns()),environment='host',timeout_seconds=timeout,workspace_id=c.workspace_id)
    c.approve_command(job['job_id'],True)
    deadline=time.monotonic()+timeout+3
    while time.monotonic()<deadline:
        result=c.command_status(job['job_id'])
        if result['state'] not in ('approved','running','pending'):return result
        time.sleep(.01)
    pytest.fail('command failed to reach a terminal state')

def test_nonzero_exit_is_failure_with_execution_evidence(tmp_path):
    c,root=fixture(tmp_path)
    try:
        result=finish(c,[sys.executable,'-c','import sys;print("failed-proof");sys.exit(7)'])
        assert result['state']=='failed'
        assert result['success'] is False and result['exit_code']==7
        assert result['started_at']<=result['finished_at']
        assert result['execution']['pid']>0
        assert 'failed-proof' in result['output']
    finally:c.close()

def test_timeout_is_distinct_from_owner_cancellation(tmp_path):
    c,_=fixture(tmp_path)
    try:
        result=finish(c,[sys.executable,'-c','import time;time.sleep(20)'],timeout=1)
        assert result['state']=='timed_out'
        assert result['success'] is False
    finally:c.close()

def test_output_cursor_returns_only_new_text(tmp_path):
    c,_=fixture(tmp_path)
    try:
        result=finish(c,[sys.executable,'-c','print("abcdef")'])
        tail=c.command_status(result['job_id'],output_offset=3)
        assert tail['output'].startswith('def')
        assert tail['next_output_offset']==len(result['output'])
        assert c.command_status(result['job_id'],output_offset=tail['next_output_offset'])['output']==''
    finally:c.close()

def test_more_than_thirty_finished_jobs_do_not_require_restart(tmp_path):
    c,_=fixture(tmp_path)
    try:
        for _ in range(32):
            result=finish(c,[sys.executable,'-c','pass'])
            assert result['exit_code']==0
    finally:c.close()


@pytest.mark.skipif(sys.platform=='win32',reason='POSIX executable aliases')
def test_host_launch_preserves_shell_alias(tmp_path):
    c,root=fixture(tmp_path)
    try:
        result=finish(c,['/bin/sh','-c','exit 7'])
        assert result['request']['argv'][0]=='/bin/sh'
        assert result['state']=='failed' and result['exit_code']==7
    finally:c.close()
