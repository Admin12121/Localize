import os
from pathlib import Path
import sys
import time
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from companion import Companion
from workspace import WorkspaceError
from bridge import rpc

def ready(tmp_path,**permissions):
    root=tmp_path/'project';root.mkdir()
    c=Companion(None,tmp_path/'runtime')
    c.configure(root=str(root),read=True,write=True,execution=True,host=True,profile={'environment':'host','shell':'powershell' if os.name=='nt' else 'sh'},**permissions)
    return c,root

def wait(c,job):
    end=time.monotonic()+10
    while time.monotonic()<end:
        result=c.command_status(job['job_id'])
        if result['state'] not in ('pending','approved','running'):return result
        time.sleep(.02)
    pytest.fail('job did not terminate')

def test_profile_selects_host_and_shell_preserves_native_failure(tmp_path):
    c,root=ready(tmp_path)
    try:
        command='cmd.exe /d /c exit 7' if os.name=='nt' else 'exit 7'
        job=c.command_request(command=command,idempotency_key='shell-native-fail',workspace_id=c.workspace_id)
        assert job['request']['environment']=='host' and job['request']['command']==command
        c.approve_command(job['job_id'],True);result=wait(c,job)
        assert result['state']=='failed' and result['exit_code']==7
        response=rpc({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'command_status','arguments':{'job_id':job['job_id']}}},c)
        assert response['result']['isError'] is True
    finally:c.close()

def test_environment_mismatch_is_not_silent_host_fallback(tmp_path):
    c,_=ready(tmp_path)
    try:
        with pytest.raises(WorkspaceError):c.command_request(['node','--version'],environment='container',idempotency_key='mismatched-mode',workspace_id=c.workspace_id)
    finally:c.close()

def test_file_operation_uses_local_approval(tmp_path):
    c,root=ready(tmp_path)
    try:
        item=c.workspace_operation('mkdir','folder/deep',workspace_id=c.workspace_id)
        assert item['approval_required'] and not (root/'folder').exists()
        assert c.local_edit(item['edit_id'])['operation']=='mkdir'
        c.approve_edit(item['edit_id'],True)
        assert (root/'folder/deep').is_dir()
    finally:c.close()

def test_durable_task_is_saved_and_completion_checks_real_files(tmp_path):
    c,root=ready(tmp_path)
    try:
        task=c.task_create('make proof',[{'kind':'file','path':'proof.txt','contains':'done'}],workspace_id=c.workspace_id)
        assert c.task_verify(task['task_id'],workspace_id=c.workspace_id)['verified'] is False
        (root/'proof.txt').write_text('done')
        assert c.task_verify(task['task_id'],workspace_id=c.workspace_id)['verified'] is True
        assert c.task_read(task['task_id'],workspace_id=c.workspace_id)['status']=='completed'
    finally:c.close()

def test_selected_integration_requires_separate_local_grant(tmp_path):
    c,_=ready(tmp_path)
    try:
        with pytest.raises(WorkspaceError):c.skill_list(workspace_id=c.workspace_id)
    finally:c.close()

def test_agent_workspace_lease_blocks_chat_mutation(tmp_path):
    c,root=ready(tmp_path)
    try:
        identity=c.workspace_snapshot();c.tasks.claim_workspace(identity,'other-agent',ttl=60)
        with pytest.raises(ValueError):c.workspace_edit('proof.txt','bad',workspace_id=c.workspace_id)
        assert not (root/'proof.txt').exists()
        c.tasks.release_workspace(identity,'other-agent')
        c.workspace_edit('proof.txt','okay',workspace_id=c.workspace_id)
    finally:c.close()


@pytest.mark.skipif(os.name!='nt',reason='Windows shell adapters')
@pytest.mark.parametrize('shell,command,filename',[
    ('powershell',"Set-Content -LiteralPath 'proof space Î©.txt' -Value 'done'",'proof space Î©.txt'),
    ('cmd','echo done>proof-cmd.txt','proof-cmd.txt'),
])
def test_shell_commands_create_files_with_real_windows_adapters(tmp_path,shell,command,filename):
    c,root=ready(tmp_path)
    try:
        job=c.command_request(command=command,shell=shell,idempotency_key='shell-real-file',workspace_id=c.workspace_id)
        c.approve_command(job['job_id'],True);result=wait(c,job)
        assert result['success'] is True,result['output']
        assert (root/filename).read_text(encoding='utf-8-sig').strip()=='done'
    finally:c.close()

@pytest.mark.skipif(os.name!='nt',reason='Windows npm launcher')
def test_npm_command_through_selected_cmd_shell_runs(tmp_path):
    import shutil
    if not shutil.which('npm'):pytest.skip('npm not installed')
    c,_=ready(tmp_path)
    try:
        job=c.command_request(command='npm --version',shell='cmd',idempotency_key='shell-real-npm',workspace_id=c.workspace_id)
        c.approve_command(job['job_id'],True);result=wait(c,job)
        assert result['success'] is True,result['output']
        assert result['output'].strip()[0].isdigit()
    finally:c.close()


def test_pause_preserves_inflight_mcp_writer_until_it_drains(tmp_path,monkeypatch):
    import threading
    c,root=ready(tmp_path,integrations=True,auto_write=True)
    entered=threading.Event();release=threading.Event();errors=[]
    def blocking_call(*args):
        entered.set();release.wait(5);return {'content':[]}
    monkeypatch.setattr(c.integrations,'call',blocking_call)
    def call():
        try:c.mcp_call('fixture','mutate',{},workspace_id=c.workspace_id)
        except ValueError as error:errors.append(str(error))
    thread=threading.Thread(target=call);thread.start()
    try:
        assert entered.wait(3)
        c.pause(True);c.pause(False)
        with pytest.raises(ValueError):c.workspace_edit('overlap.txt','bad',workspace_id=c.workspace_id)
        assert not (root/'overlap.txt').exists()
        release.set();thread.join(3)
        assert errors and 'revoked' in errors[0]
        c.workspace_edit('after.txt','good',workspace_id=c.workspace_id)
        assert (root/'after.txt').read_text()=='good'
    finally:release.set();thread.join(6);c.close()

@pytest.mark.skipif(os.environ.get('WEB_BRIDGE_DOCKER_TEST')!='1',reason='explicit real Docker fixture')
def test_switching_workspace_rejects_previous_live_docker_mapping(tmp_path):
    c,root=ready(tmp_path)
    selected=c.workspace
    try:
        c.docker_project.configure({'image':'node:24-alpine','network':'none'},selected)
        c.docker_project.action('create',selected)
        second=tmp_path/'second-project';second.mkdir()
        c.configure(root=str(second),read=True,write=True,execution=True,profile={'environment':'docker','shell':'sh'})
        with pytest.raises(WorkspaceError):c.command_request(['node','--version'],idempotency_key='stale-docker-map',workspace_id=c.workspace_id)
    finally:
        try:c.docker_project.action('remove',selected)
        finally:c.close()


@pytest.mark.skipif(os.name!='nt',reason='Windows command line serialization')
@pytest.mark.parametrize('absolute',[False,True])
def test_cmd_preserves_quoted_command_text(tmp_path,absolute):
    import shutil
    c,root=ready(tmp_path)
    executable='"'+shutil.which('node')+'"' if absolute else 'node'
    command=executable+' -e '+chr(34)+"require('fs').writeFileSync('proof cmd.txt','done')"+chr(34)
    try:
        job=c.command_request(command=command,shell='cmd',idempotency_key='cmd-quoted-command',workspace_id=c.workspace_id)
        c.approve_command(job['job_id'],True);result=wait(c,job)
        assert result['success'] is True,result['output']
        assert (root/'proof cmd.txt').read_text()=='done'
    finally:c.close()

@pytest.mark.skipif(os.name!='nt',reason='Fixture models Windows process-group cleanup; POSIX groups have separate runtime coverage')
def test_borrowed_agent_lease_survives_cancel_until_job_cleanup(tmp_path,monkeypatch):
    import threading
    from agent_runner import AgentRunner
    c,root=ready(tmp_path,auto_write=True)
    kill_started=threading.Event();release_kill=threading.Event();launched=threading.Event();jobids=[]
    class Process:
        def poll(self):return None
        def kill(self):pass
    class Group:
        def kill(self):
            kill_started.set();release_kill.wait(5)
            c.jobs.items[jobids[0]]['settled'].set()
    def launch(**arguments):
        job=c.jobs.request([sys.executable,'-c','pass'],'',60,'host','borrowed-agent-cancel',c.workspace,c.generation,False,'unused')
        key=job['job_id'];jobids.append(key);c.claim_job(key)
        c.jobs.items[key].update(state='running',process=Process(),group=Group())
        c.jobs.items[key].setdefault('settled',threading.Event())
        launched.set();return c.jobs.status(key)
    c.command_request=launch
    def provider(**kwargs):return {'calls':[{'name':'command_request','arguments':{}}],'usage':{'input_tokens':1,'output_tokens':1}}
    c.runner=AgentRunner(c.tasks,c.agent_execute,c.agent_verify,provider=provider)
    monkeypatch.setenv('WEB_BRIDGE_FIXTURE_KEY','fixture')
    c.configure_runner({'enabled':True,'model':'fixture','api_key_env':'WEB_BRIDGE_FIXTURE_KEY','max_seconds':15})
    task=c.task_create('fixture',[],workspace_id=c.workspace_id)
    cancel=None
    try:
        c.start_runner(task['task_id']);assert launched.wait(3)
        cancel=threading.Thread(target=lambda:c.jobs.cancel(jobids[0]));cancel.start();assert kill_started.wait(3)
        time.sleep(.2)
        assert c.runner.status(task['task_id'])['running'] is True
        with pytest.raises(ValueError):c.workspace_edit('overlap.txt','bad',workspace_id=c.workspace_id)
        assert not (root/'overlap.txt').exists()
    finally:
        release_kill.set()
        if cancel:cancel.join(6)
        if jobids:c.release_job(jobids[0])
        c.close()
