import builtins
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import pytest

SERVER = Path(__file__).resolve().parents[2] / 'src'
from web_bridge.integrations.registry import Integrations, IntegrationError

FIXTURE = Path(__file__).with_name('fixture_mcp_integrations.py')


def entry(**values):
    return {'type': 'mcp', 'name': 'fixture', 'transport': 'stdio',
            'command': sys.executable, 'args': [str(FIXTURE)],
            'enabled_tools': ['write_marker', 'slow', 'echo_secret', 'large'], 'timeout': 10, **values}


def test_selected_skill_resources_persist_and_cannot_escape(tmp_path):
    root = tmp_path / 'skill'; root.mkdir()
    (root / 'SKILL.md').write_text('# Selected skill', encoding='utf-8')
    (root / 'refs').mkdir(); (root / 'refs' / 'guide.md').write_text('Guide', encoding='utf-8')
    registry = Integrations(tmp_path / 'runtime')
    registry.configure([{'type': 'skill', 'name': 'selected', 'path': str(root)}])
    assert registry.skills()['skills'][0]['name'] == 'selected'
    assert registry.skill_read('selected')['text'] == '# Selected skill'
    assert registry.skill_read('selected', 'refs/guide.md')['text'] == 'Guide'
    assert Integrations(tmp_path / 'runtime').skill_read('selected')['text'] == '# Selected skill'
    for resource in ['../outside.txt', str(tmp_path / 'outside.txt'), 'refs/../../outside.txt']:
        with pytest.raises(IntegrationError): registry.skill_read('selected', resource)
    with pytest.raises(IntegrationError): registry.skill_read('unselected')


def test_skill_rejects_junction_and_binary_oversize_resources(tmp_path):
    root = tmp_path / 'skill'; root.mkdir(); (root / 'SKILL.md').write_text('ok')
    outside = tmp_path / 'outside'; outside.mkdir(); (outside / 'secret.txt').write_text('secret')
    registry = Integrations(tmp_path / 'runtime')
    registry.configure([{'type': 'skill', 'name': 'selected', 'path': str(root)}])
    link = root / 'escape'
    if os.name == 'nt':
        result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(link), str(outside)], capture_output=True)
        assert result.returncode == 0
    else: link.symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises(IntegrationError): registry.skill_read('selected', 'escape/secret.txt')
    finally:
        if os.name == 'nt': os.rmdir(link)
        else: link.unlink()
    (root / 'large.txt').write_bytes(b'x' * 256_001)
    (root / 'binary.txt').write_bytes(b'\xff')
    for resource in ['large.txt', 'binary.txt']:
        with pytest.raises(IntegrationError): registry.skill_read('selected', resource)


def test_configuration_is_atomic_allowlist_is_required_and_status_redacted(tmp_path):
    registry = Integrations(tmp_path)
    configuration = [entry(env={'TOKEN': 'local-only-secret'})]
    registry.configure(configuration)
    configuration[0]['enabled_tools'].append('unlisted')
    configuration[0]['env']['TOKEN'] = 'modified-after-configuration'
    snapshot = registry.status()
    assert 'local-only-secret' not in json.dumps(snapshot)
    assert 'command' not in json.dumps(snapshot) and 'env' not in json.dumps(snapshot)
    snapshot['servers'][0]['enabled_tools'].append('unlisted')
    assert 'unlisted' not in registry.status()['servers'][0]['enabled_tools']
    snapshot = registry.status()
    bad = entry(); del bad['enabled_tools']
    with pytest.raises(IntegrationError): registry.configure([bad])
    assert registry.status() == snapshot
    with pytest.raises(IntegrationError): registry.configure([entry(), entry()])
    with pytest.raises(IntegrationError): registry.call('fixture', 'unlisted', {})
    registry.configure([entry(enabled=False)])
    assert registry.tools() == {'tools': []}
    with pytest.raises(IntegrationError): registry.call('fixture', 'write_marker', {})


def test_missing_sdk_is_clear_and_core_skill_usage_survives(tmp_path, monkeypatch):
    registry = Integrations(tmp_path); registry.configure([entry()])
    original = builtins.__import__
    def without_mcp(name, *args, **kwargs):
        if name == 'mcp' or name.startswith('mcp.'): raise ImportError('deliberately absent')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', without_mcp)
    with pytest.raises(IntegrationError, match='requirements-integrations'):
        registry.tools('fixture')
    assert registry.skills() == {'skills': []}


def test_real_stdio_discovery_call_and_bounded_redacted_results(tmp_path):
    pytest.importorskip('mcp')
    registry = Integrations(tmp_path / 'runtime')
    registry.configure([entry(env={'FIXTURE_SECRET': 'local-only-secret'})])
    assert {t['name'] for t in registry.tools('fixture')['tools']} == {'write_marker', 'slow', 'echo_secret', 'large'}
    marker = tmp_path / 'marker.txt'
    result = registry.call('fixture', 'write_marker', {'path': str(marker), 'text': 'observable'})
    assert marker.read_text() == 'observable'
    assert result['isError'] is False
    assert 'local-only-secret' not in json.dumps(registry.call('fixture', 'echo_secret', {}))
    with pytest.raises(IntegrationError, match='limit'): registry.call('fixture', 'large', {})
    registry.close()
    with pytest.raises(IntegrationError): registry.tools('fixture')


@pytest.mark.parametrize('startup_delay',[0,4])
def test_real_stdio_timeout_does_not_replay_side_effect(tmp_path,monkeypatch,startup_delay):
    pytest.importorskip('mcp')
    import mcp.client.stdio as stdio
    processes=[]
    spawn=stdio._create_platform_compatible_process
    async def observed_spawn(*args,**kwargs):
        process=await spawn(*args,**kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(stdio,'_create_platform_compatible_process',observed_spawn)
    registry=Integrations(tmp_path/'runtime')
    registry.configure([entry(timeout=2,env={'FIXTURE_STARTUP_DELAY':str(startup_delay)})])
    marker=tmp_path/'late.txt';started=time.monotonic()
    with pytest.raises(IntegrationError,match='timed out'):
        registry.call('fixture','slow',{'path':str(marker)})
    assert time.monotonic()-started<12
    assert not marker.exists()
    # Timeout can precede tool dispatch. Observe the actual owned process,
    # rather than assuming the tool had time to write its PID file.
    assert len(processes)==1,'A timed-out request must never spawn a retry.'
    assert processes[0].returncode is not None,'Timed-out MCP subprocess survived cleanup.'


def test_credentials_are_redacted_even_when_short(tmp_path):
    pytest.importorskip('mcp')
    registry = Integrations(tmp_path)
    registry.configure([entry(env={'FIXTURE_SECRET': 'abc'})])
    result = registry.call('fixture', 'echo_secret', {})
    assert 'abc' not in json.dumps(result)


def test_skill_root_replacement_and_invalid_config_do_not_grant_access(tmp_path):
    root = tmp_path / 'skill'; root.mkdir(); (root / 'SKILL.md').write_text('first')
    registry = Integrations(tmp_path / 'runtime')
    registry.configure([{'type': 'skill', 'name': 'selected', 'path': str(root)}])
    root.rename(tmp_path / 'old-skill'); root.mkdir(); (root / 'SKILL.md').write_text('replacement')
    with pytest.raises(IntegrationError): registry.skill_read('selected')
    for invalid in [entry(timeout=float('nan')), entry(enabled_tools=None),
                    {'type': 'mcp', 'name': 'bad', 'transport': 'streamable_http',
                     'url': 'http://owner:secret@localhost/mcp', 'enabled_tools': []}]:
        with pytest.raises(IntegrationError): registry.configure([invalid])


def test_oversized_local_configuration_does_not_destroy_saved_configuration(tmp_path):
    registry = Integrations(tmp_path)
    registry.configure([entry()])
    with pytest.raises(IntegrationError, match='limit'):
        registry.configure([entry(env={f'KEY_{i}': 'x' * 16_000 for i in range(64)})])
    restored = Integrations(tmp_path)
    assert restored.status()['servers'][0]['name'] == 'fixture'


def test_invalid_tool_arguments_are_rejected_before_call(tmp_path):
    pytest.importorskip('mcp')
    registry = Integrations(tmp_path / 'runtime'); registry.configure([entry()])
    marker = tmp_path / 'invalid.txt'
    with pytest.raises(IntegrationError, match='schema'):
        registry.call('fixture', 'write_marker', {'path': str(marker), 'text': 7})
    assert not marker.exists()


def test_protocol_error_after_side_effect_is_never_replayed(tmp_path):
    pytest.importorskip('mcp')
    marker = tmp_path / 'calls.txt'
    registry = Integrations(tmp_path / 'runtime')
    registry.configure([entry(args=[str(FIXTURE), '--protocol-error'], enabled_tools=['single_effect'])])
    with pytest.raises(IntegrationError): registry.call('fixture', 'single_effect', {'path': str(marker)})
    assert marker.read_text() == 'x'


def test_external_schema_reference_cannot_fetch_or_execute(tmp_path):
    pytest.importorskip('mcp')
    marker = tmp_path / 'never-called.txt'
    registry = Integrations(tmp_path / 'runtime')
    registry.configure([entry(args=[str(FIXTURE), '--protocol-error'], enabled_tools=['external_schema'])])
    with pytest.raises(IntegrationError, match='schema'):
        registry.call('fixture', 'external_schema', {'path': str(marker)})
    assert not marker.exists()


def test_real_http_discovery_and_call(tmp_path):
    pytest.importorskip('mcp')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    process = subprocess.Popen([sys.executable, str(FIXTURE), str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.2): break
            except OSError: time.sleep(.05)
        registry = Integrations(tmp_path / 'runtime')
        registry.configure([{'type': 'mcp', 'name': 'http', 'transport': 'streamable_http',
                             'url': f'http://127.0.0.1:{port}/mcp', 'headers': {'Authorization': 'Bearer local-only-secret'},
                             'enabled_tools': ['write_marker'], 'timeout': 10}])
        assert [t['name'] for t in registry.tools('http')['tools']] == ['write_marker']
        marker = tmp_path / 'http.txt'
        registry.call('http', 'write_marker', {'path': str(marker), 'text': 'http-observable'})
        assert marker.read_text() == 'http-observable'
        assert 'local-only-secret' not in json.dumps(registry.status())
    finally:
        process.terminate(); process.wait(timeout=10)


def test_discovery_cache_is_bounded_and_invalidated_when_configuration_changes(tmp_path, monkeypatch):
    registry = Integrations(tmp_path / 'runtime')
    registry.configure([entry()])
    calls = []
    def fake_request(item, operation, tool=None, arguments=None):
        calls.append((item['name'], operation))
        return [{'server': item['name'], 'name': 'write_marker',
                 'inputSchema': {'type': 'object'}}]
    monkeypatch.setattr(registry, '_request', fake_request)
    first = registry.tools('fixture')
    first['tools'][0]['name'] = 'tampered'
    assert registry.tools('fixture')['tools'][0]['name'] == 'write_marker'
    assert len(calls) == 1
    registry.configure([entry(enabled_tools=['write_marker'])])
    assert registry.tools('fixture')['tools'][0]['name'] == 'write_marker'
    assert len(calls) == 2


def discovery_entry(tmp_path,**environment):
    return entry(args=[str(FIXTURE),'--discovery'],enabled_tools=['write_marker'],env={'FIXTURE_DISCOVERY_LOG':str(tmp_path/'discoveries'),**environment})

def test_call_then_cached_discovery_never_exposes_adapter_secrets(tmp_path):
    pytest.importorskip('mcp')
    registry=Integrations(tmp_path/'runtime')
    registry.configure([discovery_entry(tmp_path,FIXTURE_SECRET='private-adapter-secret')])
    registry.call('fixture','write_marker',{})
    assert 'private-adapter-secret' not in json.dumps(registry.tools('fixture'))

def test_discovery_cache_expiry_is_not_extended_by_calls(tmp_path,monkeypatch):
    pytest.importorskip('mcp')
    from types import SimpleNamespace
    import web_bridge.integrations.registry as module
    clock=[0.0];monkeypatch.setattr(module,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    registry=Integrations(tmp_path/'runtime');registry.configure([discovery_entry(tmp_path)])
    registry.tools('fixture');clock[0]=20
    registry.call('fixture','write_marker',{})
    after_call=len((tmp_path/'discoveries').read_text().splitlines());clock[0]=31
    registry.tools('fixture')
    assert len((tmp_path/'discoveries').read_text().splitlines())>after_call

def test_partial_discovery_after_ten_pages_is_rejected(tmp_path):
    pytest.importorskip('mcp')
    registry=Integrations(tmp_path/'runtime')
    registry.configure([discovery_entry(tmp_path,FIXTURE_PAGES='11')])
    with pytest.raises(IntegrationError,match='pagination'):
        registry.tools('fixture')
