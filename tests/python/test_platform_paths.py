"""Platform-independent path and launcher contracts (CI: Linux, Windows, macOS)."""
from pathlib import Path
import web_bridge.runtime as runtime
from web_bridge.execution.jobs import minimal_environment


def test_runtime_paths_for_all_supported_platforms(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.delenv('XDG_STATE_HOME', raising=False)
    monkeypatch.delenv('LOCALAPPDATA', raising=False)
    for platform, expected in (
        ('win32', tmp_path / 'AppData/Local/Web-Bridge/runtime'),
        ('darwin', tmp_path / 'Library/Application Support/Web-Bridge/runtime'),
        ('linux', tmp_path / '.local/state/web-bridge'),
    ):
        monkeypatch.setattr(runtime.sys, 'platform', platform)
        assert runtime.runtime_home() == expected
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    monkeypatch.setattr(runtime.sys, 'platform', 'linux')
    assert runtime.runtime_home() == tmp_path / 'state/web-bridge'


def test_docker_config_passes_to_restricted_execution_environment(monkeypatch, tmp_path):
    config = str(tmp_path / 'custom-docker-config')
    monkeypatch.setenv('DOCKER_CONFIG', config)
    environment = minimal_environment()
    assert environment['DOCKER_CONFIG'] == config
    assert environment['PYTHONNOUSERSITE'] == '1'
