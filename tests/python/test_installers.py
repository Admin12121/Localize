"""Exercise real isolated uv installs while supplying local release downloads."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
WHEEL = 'localizeit-3.2.1-py3-none-any.whl'


@pytest.mark.parametrize('checksum', ['valid', 'mismatch', 'missing', 'duplicate'])
def test_installer_verifies_release_before_registering_command(tmp_path, checksum):
    uv = shutil.which('uv')
    if not uv:
        pytest.skip('uv is required for installer integration tests')
    fixture = tmp_path/'release'; fixture.mkdir()
    data = (ROOT/'dist/release'/WHEEL).read_bytes()
    (fixture/WHEEL).write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    line = f'{digest}  {WHEEL}\n'
    if checksum == 'mismatch': line = f'{"0"*64}  {WHEEL}\n'
    if checksum == 'missing': line = f'{digest}  another-wheel.whl\n'
    if checksum == 'duplicate': line += line
    (fixture/'SHA256SUMS').write_text(line,encoding='utf-8')
    # Spaces in the command directory and temp paths must survive both shells.
    tool_bin = tmp_path/'installed commands'
    env = {**os.environ, 'PATH':str(Path(uv).parent)+os.pathsep+os.environ['PATH'],
           'UV_TOOL_DIR':str(tmp_path/'tools'), 'UV_TOOL_BIN_DIR':str(tool_bin),
           'UV_CACHE_DIR':str(tmp_path/'cache'), 'LOCALIZEIT_FIXTURE_DIR':str(fixture),
           'LOCALIZEIT_PYTHON':sys.executable, 'PYTHONDONTWRITEBYTECODE':'1'}
    if os.name == 'nt':
        env['LOCALIZEIT_INSTALLER'] = str(ROOT/'scripts/install.ps1')
        wrapper = tmp_path/'run.ps1'
        wrapper.write_text('''$ErrorActionPreference = 'Stop'
function Invoke-WebRequest {
    param($UseBasicParsing, $Uri, $OutFile, $TimeoutSec)
    if (-not $Uri.StartsWith('https://github.com/Admin12121/Localize/releases/download/v3.2.1/')) { throw 'Unexpected download host.' }
    Copy-Item -LiteralPath (Join-Path $env:LOCALIZEIT_FIXTURE_DIR ([IO.Path]::GetFileName(([Uri]$Uri).AbsolutePath))) -Destination $OutFile
}
& $env:LOCALIZEIT_INSTALLER -NoModifyPath -Python $env:LOCALIZEIT_PYTHON
'''.replace('param($UseBasicParsing,','param([switch]$UseBasicParsing,'),encoding='utf-8')
        command = ['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(wrapper)]
    else:
        mock_bin = tmp_path/'download adapter'; mock_bin.mkdir()
        curl = mock_bin/'curl'
        curl.write_text('''#!/usr/bin/env python3
import os, pathlib, shutil, sys
args=sys.argv[1:]
url=next(arg for arg in args if arg.startswith('https://'))
assert url.startswith('https://github.com/Admin12121/Localize/releases/download/v3.2.1/')
shutil.copyfile(pathlib.Path(os.environ['LOCALIZEIT_FIXTURE_DIR'])/url.rsplit('/',1)[1],args[args.index('--output')+1])
''',encoding='utf-8')
        curl.chmod(0o700)
        env['PATH'] = str(mock_bin)+os.pathsep+env['PATH']
        command = ['sh',str(ROOT/'scripts/install.sh'),'--no-modify-path']
    result = subprocess.run(command,env=env,capture_output=True,text=True,encoding='utf-8',timeout=90)
    executable = tool_bin/('localizeit.exe' if os.name=='nt' else 'localizeit')
    if checksum != 'valid':
        assert result.returncode != 0
        assert not executable.exists()
        assert 'checksum' in (result.stdout+result.stderr).lower()
        return
    assert result.returncode == 0, result.stdout+result.stderr
    assert executable.is_file()
    about = subprocess.run([str(executable),'--about'],env=env,capture_output=True,text=True,encoding='utf-8',timeout=15)
    assert about.returncode == 0,about.stderr
    assert json.loads(about.stdout)['version']=='3.2.1'
    assert 'localizeit' in result.stdout
