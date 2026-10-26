"""Persistent Docker project contracts; real-engine checks are opt-in."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from web_bridge.execution.docker import DockerProject
from web_bridge.workspace.files import Workspace, WorkspaceError


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / 'project'; root.mkdir()
    workspace = Workspace(root)
    docker = DockerProject(tmp_path / 'runtime')
    calls = []
    state = {'endpoint': 'unix:///var/run/docker.sock', 'running': True,
             'mount': str(root), 'image': True, 'id': 'a' * 64, 'labels': {}}

    def invoke(args, timeout=30):
        calls.append(list(args))
        if args[:2] == ['context', 'show']: return 'desktop-linux'
        if args[:2] == ['context', 'inspect']:
            return json.dumps([{'Endpoints': {'docker': {'Host': state['endpoint']}}}])
        if args[0] == 'info': return json.dumps({'OSType': 'linux'})
        if args[:2] == ['image', 'inspect']:
            if not state['image']: raise WorkspaceError('Image is missing; explicitly pull or prepare it locally.')
            return '[{}]'
        if args[:2] == ['container', 'inspect']:
            return json.dumps([{'Id': state['id'], 'State': {'Running': state['running']},
                'Config': {'User': '', 'Labels': state['labels']},
                'HostConfig': {'Privileged': False, 'CapAdd': [], 'NetworkMode': 'bridge'},
                'Mounts': [{'Type': 'bind', 'Source': state['mount'],
                            'Destination': '/workspace', 'RW': True}]}])
        if args[:2] == ['container', 'create']:
            for index, value in enumerate(args):
                if value == '--label':
                    key, val = args[index + 1].split('=', 1); state['labels'][key] = val
            return state['id']
        return ''

    monkeypatch.setattr(docker, '_invoke', invoke)
    monkeypatch.setattr(docker, '_binary', 'docker')
    return docker, workspace, calls, state


def configure(project, **extra):
    docker, workspace, _, _ = project
    return docker.configure({'context': 'desktop-linux', 'image': 'node:24-alpine', **extra}, workspace)


def test_configuration_is_local_persistent_and_status_redacts_host_paths(project):
    docker, workspace, calls, _ = project
    result = configure(project)
    assert result['configured'] and result['image_ready']
    assert str(workspace.root) not in json.dumps(result)
    assert not any(args[0] in ('pull', 'run') for args in calls)
    saved = json.loads(docker.path.read_text())
    assert saved['config']['context'] == 'desktop-linux'
    assert 'auth' not in json.dumps(saved).lower()


def test_default_context_discovery_does_not_override_the_owners_active_context(project, monkeypatch):
    docker, workspace, _, _ = project
    original = docker._invoke
    seen = []
    def invoke(args, timeout=30):
        if args == ['context', 'show']:
            seen.append(docker._command(args))
        return original(args, timeout)
    monkeypatch.delenv('DOCKER_CONTEXT', raising=False)
    monkeypatch.delenv('DOCKER_HOST', raising=False)
    monkeypatch.setattr(docker, '_invoke', invoke)
    assert docker.configure({'image': 'node:24-alpine'}, workspace)['context'] == 'desktop-linux'
    assert '--config' in seen[0] and '--context' not in seen[0]


def test_configure_refuses_to_silently_discard_a_host_override(project, monkeypatch):
    docker, workspace, _, _ = project
    monkeypatch.setenv('DOCKER_HOST', 'tcp://other-machine:2375')
    monkeypatch.delenv('DOCKER_CONTEXT', raising=False)
    with pytest.raises(WorkspaceError, match='explicit.*context'):
        docker.configure({'image': 'node:24-alpine'}, workspace)


def test_remote_context_rejected_and_changed_endpoint_never_mutates(project):
    docker, workspace, calls, state = project
    state['endpoint'] = 'tcp://server:2375'
    with pytest.raises(WorkspaceError, match='local'): configure(project)
    state['endpoint'] = 'unix:///var/run/docker.sock'; configure(project)
    state['endpoint'] = 'unix:///different.sock'
    calls.clear()
    with pytest.raises(WorkspaceError, match='changed'): docker.action('create', workspace)
    assert not any(args[:2] == ['container', 'create'] for args in calls)


def test_missing_image_never_pulls_implicitly(project):
    docker, workspace, calls, state = project
    state['image'] = False
    assert not configure(project)['image_ready']
    with pytest.raises(WorkspaceError, match='Image'): docker.action('create', workspace)
    assert not any(args[0] == 'pull' for args in calls)


def test_attach_requires_exact_writable_project_mount_and_preserves_unowned_container(project):
    docker, workspace, calls, state = project
    configure(project)
    state['mount'] += '-other'
    with pytest.raises(WorkspaceError, match='mount'): docker.action('attach', workspace, container='existing')
    state['mount'] = str(workspace.root)
    result = docker.action('attach', workspace, container='existing')
    assert result['mode'] == 'attached' and not result['owned']
    for action in ('stop', 'remove'):
        with pytest.raises(WorkspaceError, match='owned'): docker.action(action, workspace)
    assert not any(args[:2] in (['container', 'stop'], ['container', 'rm']) for args in calls)


def test_create_records_ownership_and_exec_revalidates_identity_mount_and_cwd(project):
    docker, workspace, calls, state = project
    configure(project); docker.action('create', workspace)
    assert docker.status()['owned']
    command = docker.build_command('job-one', ['node', '-e', 'process.exit(7)'], '')
    assert command[:1] == ['docker'] and '--context' in command
    assert '--workdir' in command and '/workspace' in command
    assert state['id'] in command and command[-3:] == ['node', '-e', 'process.exit(7)']
    state['id'] = 'b' * 64
    with pytest.raises(WorkspaceError, match='identity'): docker.build_command('job-two', ['pwd'], '')


def test_mount_change_and_workspace_replacement_block_exec(project):
    docker, workspace, _, state = project
    configure(project); docker.action('attach', workspace, container='existing')
    state['mount'] += '-other'
    with pytest.raises(WorkspaceError, match='mount'): docker.build_command('job', ['pwd'], '')
    state['mount'] = str(workspace.root)
    workspace.root.rename(workspace.root.with_name('old'))
    workspace.root.mkdir()
    with pytest.raises(WorkspaceError, match='replaced|changed'): docker.build_command('job', ['pwd'], '')


def test_privileged_attachment_requires_explicit_local_broad_access_grant(project, monkeypatch):
    docker, workspace, _, _ = project
    configure(project)
    original = docker._invoke
    def privileged(args, timeout=30):
        value = original(args, timeout)
        if args[:2] == ['container', 'inspect']:
            info = json.loads(value); info[0]['HostConfig']['Privileged'] = True
            return json.dumps(info)
        return value
    monkeypatch.setattr(docker, '_invoke', privileged)
    with pytest.raises(WorkspaceError, match='broad'): docker.action('attach', workspace, container='existing')
    assert docker.action('attach', workspace, container='existing', allow_broad_access=True)['mode'] == 'attached'


def test_argv_cwd_and_unknown_cancel_are_bounded(project):
    docker, workspace, _, _ = project
    configure(project); docker.action('attach', workspace, container='existing')
    assert docker.cancel('unknown') is False
    with pytest.raises(WorkspaceError): docker.build_command('job', ['pwd'], '../escape')
    with pytest.raises(WorkspaceError): docker.build_command('job', 'echo hi', '')


def test_finish_forgets_terminal_tokens_without_touching_the_container(project):
    docker, workspace, calls, _ = project
    configure(project); docker.action('attach', workspace, container='existing')
    docker.build_command('finished-job', ['pwd'], '')
    calls.clear()
    assert docker.finish('finished-job') is True
    assert docker.finish('finished-job') is False
    assert docker.cancel('finished-job') is False
    assert calls == []


def test_ownership_survives_restart_and_container_labels_must_match(project):
    docker, workspace, _, state = project
    configure(project); docker.action('create', workspace)
    restarted = DockerProject(docker.path.parent)
    restarted._invoke = docker._invoke; restarted._binary = 'docker'
    assert restarted.status()['owned']
    state['labels'] = {}
    with pytest.raises(WorkspaceError, match='ownership'): restarted.action('stop', workspace)


def test_native_errors_do_not_leak_docker_paths_or_credentials(tmp_path, monkeypatch):
    docker = DockerProject(tmp_path / 'runtime')
    docker._binary = 'docker'
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs:
        subprocess.CompletedProcess(args[0], 1, '', 'secret-password /private/docker/config.json'))
    with pytest.raises(WorkspaceError, match='engine is unavailable') as error:
        docker._invoke(['info'])
    assert 'secret-password' not in str(error.value) and '/private' not in str(error.value)


def test_missing_selection_is_distinct_from_engine_failure_and_can_be_detached(project, monkeypatch):
    docker, workspace, calls, _ = project
    configure(project)
    docker.action('create', workspace)
    invoke = docker._invoke

    def missing(args, timeout=30):
        if args[:2] == ['container', 'inspect']:
            return DockerProject._invoke(docker, args, timeout)
        return invoke(args, timeout)

    monkeypatch.setattr(docker, '_invoke', missing)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw:
        subprocess.CompletedProcess(a[0], 1, '', 'Error: No such object: ' + 'a' * 64))
    result = docker.status()
    assert result.get('container_missing') is True
    assert not result['ready'] and 'Recreate' in result['error']
    calls.clear()
    assert docker.action('detach', workspace)['container_id'] is None
    assert not any(c[:2] in (['container', 'rm'], ['container', 'stop']) for c in calls)


def test_inspection_access_failure_never_claims_the_container_is_missing(project, monkeypatch):
    docker, workspace, _, _ = project
    configure(project)
    docker.action('create', workspace)
    invoke = docker._invoke

    def unavailable(args, timeout=30):
        if args[:2] == ['container', 'inspect']:
            return DockerProject._invoke(docker, args, timeout)
        return invoke(args, timeout)

    monkeypatch.setattr(docker, '_invoke', unavailable)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw:
        subprocess.CompletedProcess(a[0], 1, '', 'permission denied: /private/docker/config.json token=secret'))
    result = docker.status()
    assert not result.get('container_missing')
    assert not result['ready']
    assert 'secret' not in result['error'] and '/private' not in result['error']


def test_stopped_container_reports_exit_and_memory_recovery_without_raw_engine_error(project, monkeypatch):
    docker, workspace, _, state = project
    configure(project)
    docker.action('create', workspace)
    invoke = docker._invoke

    def stopped(args, timeout=30):
        value = invoke(args, timeout)
        if args[:2] == ['container', 'inspect']:
            info = json.loads(value)
            info[0]['State'] = {'Running': False, 'Status': 'exited', 'ExitCode': 137,
                                'OOMKilled': True, 'Error': 'secret engine details'}
            return json.dumps(info)
        return value

    monkeypatch.setattr(docker, '_invoke', stopped)
    result = docker.status()
    assert result.get('exit_code') == 137
    assert result.get('oom_killed') is True
    assert 'memory' in result['error'].lower() and 'secret' not in result['error']


@pytest.mark.skipif(os.environ.get('WEB_BRIDGE_DOCKER_TEST') != '1', reason='Explicit real local Docker fixture')
def test_real_docker_persistent_mount_and_attached_command_cancellation(tmp_path):
    root = tmp_path / 'docker-roundtrip'; root.mkdir()
    workspace = Workspace(root)
    (root / 'roundtrip.txt').write_text('from-host', encoding='utf-8')
    docker = DockerProject(tmp_path / 'docker-runtime')
    docker.configure({'image': 'node:24-alpine'}, workspace)
    created = None; unrelated = None; running = None
    try:
        result = docker.action('create', workspace); created = result['container_id']
        command = docker.build_command('roundtrip', ['node', '-e',
            "const fs=require('fs'); if(fs.readFileSync('roundtrip.txt','utf8')!=='from-host')process.exit(3); fs.writeFileSync('roundtrip.txt','from-container'); console.log(process.cwd());"], '')
        completed = subprocess.run(command, capture_output=True, text=True, timeout=20)
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.strip() == '/workspace'
        assert (root / 'roundtrip.txt').read_text() == 'from-container'
        attached = DockerProject(tmp_path / 'attached-runtime')
        attached.configure({'image': 'node:24-alpine'}, workspace)
        assert not attached.action('attach', workspace, container=created)['owned']
        unrelated = subprocess.Popen(docker._command(['exec', created, 'sh', '-c', 'sleep 60']), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        running = subprocess.Popen(attached.build_command('cancel-me', ['node', '-e',
            "const fs=require('fs'),cp=require('child_process'); const child=cp.spawn('node',['-e',`setTimeout(()=>require('fs').writeFileSync('escaped.txt','bad'),2500);setInterval(()=>{},1000)`]);fs.writeFileSync('started.txt',JSON.stringify({pid:process.pid,child:child.pid}));setInterval(()=>{},1000)"], ''), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 10
        while not (root / 'started.txt').exists() and time.monotonic() < deadline: time.sleep(.05)
        assert (root / 'started.txt').exists()
        assert attached.cancel('cancel-me')
        running.wait(timeout=10)
        identities = json.loads((root / 'started.txt').read_text())
        check = subprocess.run(docker._command(['exec', created, 'sh', '-c',
            'for p in "$@"; do test ! -e /proc/$p/stat || test "$(awk \'{print $3}\' /proc/$p/stat)" = Z || exit 1; done',
            'check-owned', str(identities['pid']), str(identities['child'])]), capture_output=True, timeout=10)
        assert check.returncode == 0, check.stderr
        assert unrelated.poll() is None
        for action in ('stop', 'remove'):
            with pytest.raises(WorkspaceError, match='owned'): attached.action(action, workspace)
        assert docker.status()['running']
        assert docker.action('logs', workspace)['logs'] == ''
    finally:
        if created:
            docker.action('remove', workspace)
        for process in (running, unrelated):
            if process is not None:
                try: process.communicate(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.communicate(timeout=5)



def test_reconfiguration_cannot_silently_reuse_container_with_different_settings(project):
    docker, workspace, _, _ = project
    configure(project)
    docker.action('create', workspace)
    original = dict(docker._config)
    for change in ({'image': 'python:3.12-alpine'}, {'network': 'none'},
                   {'cpus': 3}, {'memory': '4g'}, {'pids_limit': 512},
                   {'workdir': '/source'}):
        with pytest.raises(WorkspaceError, match='previous settings'):
            docker.configure({'context': 'desktop-linux', 'image': 'node:24-alpine',
                              **change}, workspace)
        assert docker._config == original
    assert configure(project)['container_id'] == original['container_id']


def test_detach_preserves_managed_container_and_allows_new_settings(project):
    docker, workspace, calls, _ = project
    configure(project)
    docker.action('create', workspace)
    calls.clear()
    result = docker.action('detach', workspace)
    assert result['container_id'] is None
    assert not any(args[:2] in (['container', 'stop'], ['container', 'rm']) for args in calls)
    assert docker.configure({'context': 'desktop-linux', 'image': 'python:3.12-alpine'}, workspace)['image'] == 'python:3.12-alpine'


def test_restart_restores_workspace_reference_for_subdirectories(project):
    docker, workspace, _, state = project
    (workspace.root / 'nested').mkdir()
    configure(project)
    docker.action('attach', workspace, container='existing')
    restarted = DockerProject(docker.path.parent)
    restarted._invoke = docker._invoke
    restarted._binary = 'docker'
    restarted.validate_workspace(workspace)
    command = restarted.build_command('after-restart', ['pwd'], 'nested')
    assert '/workspace/nested' in command


def test_local_status_can_reconfigure_containerless_mapping_for_new_project(project, tmp_path):
    docker, workspace, _, _ = project
    configure(project)
    other = tmp_path / 'other-project'
    other.mkdir()
    selected = Workspace(other)
    result = docker.status(selected)
    assert result['workspace_matches'] is False and result['container_id'] is None
    assert not result['ready']
    assert docker.configure({'context': 'desktop-linux'}, selected)['workspace_matches']


def test_forget_selection_preserves_old_container_after_workspace_switch(project, tmp_path):
    docker, workspace, calls, _ = project
    configure(project)
    docker.action('create', workspace)
    other = tmp_path / 'other-project'
    other.mkdir()
    selected = Workspace(other)
    calls.clear()
    assert docker.action('detach', selected)['container_id'] is None
    assert not any(args[0] == 'container' for args in calls)
    assert docker.configure({'context': 'desktop-linux'}, selected)['workspace_matches']


def test_recreation_preserves_locally_saved_resource_limits_and_docker_configuration(project, tmp_path):
    docker, workspace, _, _ = project
    configure(project, cpus=1, memory='512m', pids_limit=64, docker_config=str(tmp_path/'docker-settings'))
    docker.action('create', workspace)
    docker.action('detach', workspace)
    docker.configure({'context':'desktop-linux', 'image':'node:24-alpine',
                      'workdir':'/workspace', 'network':'bridge'}, workspace)
    assert docker._config['cpus'] == 1
    assert docker._config['memory'] == '512m'
    assert docker._config['pids_limit'] == 64
    assert docker._config['docker_config'] == str(tmp_path/'docker-settings')


@pytest.mark.skipif(os.environ.get('WEB_BRIDGE_DOCKER_TEST') != '1', reason='Explicit real local Docker fixture')
def test_real_docker_missing_container_recovery_keeps_project_files_and_limits(tmp_path):
    root = tmp_path/'recovery-project'
    root.mkdir()
    (root/'proof.txt').write_text('before recovery', encoding='utf-8')
    workspace = Workspace(root)
    docker = DockerProject(tmp_path/'recovery-runtime')
    created = []
    try:
        docker.configure({'image':'node:24-alpine','network':'none',
                          'cpus':1,'memory':'512m','pids_limit':64}, workspace)
        created.append(docker.action('create', workspace)['container_id'])
        docker._invoke(['container','rm','--force',created[-1]])
        missing = docker.status()
        assert missing['container_missing'] and not missing['ready']
        docker.action('detach', workspace)
        docker.configure({'image':'node:24-alpine','network':'none'}, workspace)
        ready = docker.action('create', workspace)
        created.append(ready['container_id'])
        assert ready['ready'] and ready['cpus'] == 1 and ready['memory'] == '512m'
        assert ready['pids_limit'] == 64
        command = docker.build_command('after-recovery', ['node','-e',
            "const fs=require('fs');if(fs.readFileSync('proof.txt','utf8')!=='before recovery')process.exit(3);fs.writeFileSync('proof.txt','after recovery');console.log(process.cwd())"], '')
        result = subprocess.run(command,capture_output=True,text=True,timeout=20)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == '/workspace'
        assert (root/'proof.txt').read_text() == 'after recovery'
        docker.finish('after-recovery')
    finally:
        for container in created:
            subprocess.run(docker._command(['container','rm','--force',container]),
                           capture_output=True,timeout=15)
