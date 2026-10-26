import sys
import time
from pathlib import Path
import pytest
from web_bridge.app import Companion
from web_bridge.workspace.files import WorkspaceError

def ready(tmp_path):
    root=tmp_path/'repo';root.mkdir();(root/'main.py').write_text('print(1)')
    c=Companion(None,tmp_path/'runtime')
    c.configure(root=str(root),read=True,write=True,execution=True,host=True)
    return c,root

def test_disabled_access_and_read_write_local_approval(tmp_path):
    c=Companion(None,tmp_path/'runtime')
    with pytest.raises(WorkspaceError): c.workspace_list()
    root=tmp_path/'repo';root.mkdir();(root/'a.txt').write_text('before')
    c.configure(root=str(root),read=True,write=True)
    original=c.workspace_read('a.txt',workspace_id=c.bridge_status()['workspace_id'])
    edit=c.workspace_edit('a.txt','after',original['sha256'],workspace_id=c.bridge_status()['workspace_id'])
    assert (root/'a.txt').read_text()=='before'
    assert c.approve_edit(edit['edit_id'],True)['applied']
    assert (root/'a.txt').read_text()=='after'
    c.pause(True)
    with pytest.raises(WorkspaceError):c.workspace_read('a.txt',workspace_id=c.bridge_status()['workspace_id'])

def test_host_commands_are_pending_single_use_and_real(tmp_path):
    c,root=ready(tmp_path)
    req=c.command_request([sys.executable,'-c','print("real-host-result")'],idempotency_key='host-test-0001',environment='host',workspace_id=c.bridge_status()['workspace_id'])
    assert req['state']=='pending'
    assert c.command_request([sys.executable,'-c','print("real-host-result")'],idempotency_key='host-test-0001',environment='host',workspace_id=c.bridge_status()['workspace_id'])['job_id']==req['job_id']
    with pytest.raises(WorkspaceError):c.command_request([sys.executable,'-c','print("changed")'],idempotency_key='host-test-0001',environment='host',workspace_id=c.bridge_status()['workspace_id'])
    c.approve_command(req['job_id'],True)
    with pytest.raises(WorkspaceError):c.approve_command(req['job_id'],True)
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        result=c.command_status(req['job_id'])
        if result['state'] not in ('approved','running'):break
        time.sleep(.02)
    assert result['state']=='completed' and result['exit_code']==0
    assert 'real-host-result' in result['output']
    c.close()

def test_policy_change_revokes_pending_and_host_is_opt_in(tmp_path):
    c,root=ready(tmp_path)
    req=c.command_request([sys.executable,'-c','print(1)'],idempotency_key='host-test-0002',environment='host',workspace_id=c.bridge_status()['workspace_id'])
    c.configure(root=str(root),read=True,execution=True,host=False)
    with pytest.raises(WorkspaceError):c.approve_command(req['job_id'],True)
    with pytest.raises(WorkspaceError):c.command_request([sys.executable,'-c','print(1)'],idempotency_key='host-test-0003',environment='host',workspace_id=c.bridge_status()['workspace_id'])
    c.close()

def test_approval_expires_and_status_cannot_mutate_queued_command(tmp_path):
    c,_=ready(tmp_path)
    argv=[sys.executable,'-c','print(1)']
    job=c.command_request(argv,idempotency_key='expiry-fixture-1',environment='host',workspace_id=c.bridge_status()['workspace_id'])
    argv[-1]='print(2)';job['request']['argv'][-1]='print(3)'
    assert c.command_status(job['job_id'])['request']['argv'][-1]=='print(1)'
    c.jobs.items[job['job_id']]['expires']=time.monotonic()-1
    with pytest.raises(WorkspaceError):c.approve_command(job['job_id'],True)
    assert c.command_status(job['job_id'])['state']=='expired'
    c.close()

def test_stale_workspace_and_revoked_job_results_are_rejected(tmp_path):
    c,root=ready(tmp_path)
    workspace_id=c.bridge_status()['workspace_id']
    job=c.command_request([sys.executable,'-c','print("old-result")'],idempotency_key='revoked-results-1',environment='host',workspace_id=workspace_id)
    c.approve_command(job['job_id'],True)
    deadline=time.monotonic()+5
    while c.command_status(job['job_id'])['state'] in ('approved','running') and time.monotonic()<deadline:time.sleep(.02)
    c.pause(True)
    assert 'output' not in c.command_cancel(job['job_id'])
    c.pause(False);c.configure(root=str(root),read=True,write=True,execution=True,host=True)
    with pytest.raises(WorkspaceError):c.command_status(job['job_id'])
    with pytest.raises(WorkspaceError):c.workspace_edit('new.txt','stale',workspace_id=workspace_id)
    c.close()

def test_cancel_kills_ordinary_child_after_parent_exits(tmp_path):
    import json
    c,root=ready(tmp_path);marker=root/'child-survived.txt'
    child=f'import time;from pathlib import Path;time.sleep(4);Path({str(marker)!r}).write_text("survived")'
    parent=f'import subprocess,sys;p=subprocess.Popen([sys.executable,"-c",{child!r}]);print("child-started",flush=True)'
    job=c.command_request([sys.executable,'-c',parent],idempotency_key='child-cancel-01',environment='host',workspace_id=c.bridge_status()['workspace_id'])
    c.approve_command(job['job_id'],True)
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        process=c.jobs.items[job['job_id']]['process']
        if process and process.poll() is not None:break
        time.sleep(.02)
    c.pause(True);time.sleep(4.3)
    assert not marker.exists()
    c.close()

def test_ctf_batch_stops_before_next_dispatch_after_pause(tmp_path,monkeypatch):
    from web_bridge.web.client import Bridge
    network=Bridge({'fixture':'https://example.invalid'})
    c=Companion(network,tmp_path/'runtime');sent=[]
    def request(*args,**kwargs):
        sent.append(1);c.pause(True);return {'status':200}
    monkeypatch.setattr(network,'http_request',request)
    with pytest.raises(Exception):c.http_batch(target='fixture',requests=[{}, {}, {}])
    assert len(sent)==1
    c.close()

def test_container_invocation_has_snapshot_only_and_no_network(tmp_path):
    from web_bridge.execution.jobs import container_arguments
    args=container_arguments('safe-job',tmp_path/'stage','python:3.12-alpine',['python','-V'],network=False)
    assert '--network=none' in args and '--read-only' in args
    assert '--cap-drop=ALL' in args and '--security-opt=no-new-privileges' in args
    assert '--pull=never' in args
    assert not any('docker.sock' in x or '--privileged' in x for x in args)

def test_pause_cancels_running_host_process(tmp_path):
    c,_=ready(tmp_path)
    req=c.command_request([sys.executable,'-c','import time;time.sleep(60)'],idempotency_key='host-cancel-1',environment='host',workspace_id=c.bridge_status()['workspace_id'])
    c.approve_command(req['job_id'],True)
    deadline=time.monotonic()+5
    while c.command_status(req['job_id'])['state']!='running' and time.monotonic()<deadline:time.sleep(.02)
    c.pause(True)
    assert c.jobs.status(req['job_id'])['state']=='cancelled'
    c.close()

def test_real_container_has_filtered_copy_and_changes_require_approval(tmp_path):
    import os
    if os.environ.get('WEB_BRIDGE_DOCKER_TEST')!='1':pytest.skip('Explicit real Docker fixture is opt-in.')
    c,root=ready(tmp_path);(root/'.env').write_text('must-not-enter-container')
    for i in range(25):(root/f'image-{i}.png').write_bytes(b'\x89PNG\x00unchanged')
    c.configure(root=str(root),read=True,write=True,execution=True,image='node:24-alpine')
    code="const fs=require('fs');if(fs.existsSync('.env'))process.exit(9);fs.writeFileSync('result.txt','container-result');console.log('filtered-container-ok')"
    job=c.command_request(['node','-e',code],idempotency_key='container-real-1',workspace_id=c.bridge_status()['workspace_id'])
    c.approve_command(job['job_id'],True)
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        result=c.command_status(job['job_id'])
        if result['state'] not in ('approved','running'):break
        time.sleep(.1)
    assert result['state']=='completed' and result['exit_code']==0, result['output']
    assert 'filtered-container-ok' in result['output']
    assert not (root/'result.txt').exists()
    edit=next(x for x in result['changes'] if x.get('path')=='result.txt')
    c.approve_edit(edit['edit_id'],True)
    assert (root/'result.txt').read_text()=='container-result'
    c.close()

def test_activity_summary_is_bounded_and_detail_is_lazy(tmp_path):
    import json
    c,_=ready(tmp_path)
    job=c.command_request([sys.executable,'-c','print(1)'],idempotency_key='summary-test-01',environment='host',workspace_id=c.bridge_status()['workspace_id'])
    c.jobs.items[job['job_id']]['output']='x'*65536
    summary=c.local_state()
    assert 'output' not in summary['jobs'][0]
    assert 'request' not in summary['jobs'][0]
    assert summary['jobs'][0]['output_length']==65536
    assert len(json.dumps(summary))<2500
    assert c.jobs.status(job['job_id'])['output']=='x'*65536
    assert c.bridge_status()['pending_commands']==1
    c.jobs.items[job['job_id']]['expires']=time.monotonic()-1
    assert c.local_state()['jobs'][0]['state']=='expired'
    assert c.bridge_status()['pending_commands']==0
    c.close()


def test_ai_working_context_reflects_owner_grants_without_probing(tmp_path):
    from web_bridge.app import Companion
    root = tmp_path / 'source'
    root.mkdir()
    c = Companion(None, tmp_path / 'runtime')
    try:
        context = c.bridge_status()['working_context']
        assert context['workspace_selected'] is False
        assert context['command']['allowed'] is False
        assert context['integrations']['adapters'] == []
        assert context['desktop']['general_control'] is False
        c.configure(root=str(root), read=True, execution=True, host=False,
                    integrations=True, profile={'environment': 'container', 'shell': 'sh'})
        context = c.bridge_status()['working_context']
        assert context['can_read'] is True
        assert context['can_edit'] is False
        assert context['command']['mode'] == 'isolated_snapshot'
        assert context['command']['docker_preflight_required'] is True
        c.integration_add({'type': 'mcp', 'name': 'local_editor',
                           'transport': 'stdio', 'command': 'mock-tool',
                           'enabled_tools': ['read_document'], 'timeout': 10})
        assert c.bridge_status()['working_context']['integrations']['adapters'][0]['tools'] == ['read_document']
        c.pause(True)
        assert c.bridge_status()['working_context']['integrations']['adapters'] == []
        assert c.bridge_status()['working_context']['command']['allowed'] is False
    finally:
        c.close()


def test_working_context_does_not_offer_integrations_after_project_is_deselected(tmp_path):
    root=tmp_path/'project';root.mkdir();c=Companion(None,tmp_path/'runtime')
    try:
        c.configure(root=str(root),read=True,integrations=True)
        c.integration_add({'type':'mcp','name':'editor','transport':'stdio','command':'fixture','enabled_tools':['read']})
        assert 'web-bridge-project-work' in c.bridge_status()['working_context']['integrations']['skills']
        c.configure(root='',read=False,integrations=True)
        context=c.bridge_status()['working_context']['integrations']
        assert context['enabled'] is False and context['adapters']==[] and context['skills']==[]
    finally:c.close()
