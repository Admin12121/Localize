"""Release behavior must not depend on files outside the exported packages."""
from pathlib import Path
from zipfile import ZipFile
import json
import os
import sqlite3
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
RELEASE=ROOT/'dist/release'

def test_portable_source_contains_applicable_migration_and_no_build_metadata():
    with ZipFile(RELEASE/'web-bridge-portable-source.zip') as archive:
        migration=archive.read('web-bridge-source/gateway/drizzle/0000_calm_jackal.sql').decode('utf-8')
        assert not any('.egg-info/' in n or '/build/' in n for n in archive.namelist())
    db=sqlite3.connect(':memory:')
    try:
        db.executescript(migration)
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='connections'").fetchone()
    finally:db.close()

def test_extracted_companion_runs_and_reads_bundled_skill_and_ui(tmp_path):
    with ZipFile(RELEASE/'web-bridge-companion.zip') as archive:archive.extractall(tmp_path)
    extracted=tmp_path/'web-bridge-companion'
    about=subprocess.run([sys.executable,'-B',str(extracted/'scripts/run.py'),'--about'],cwd=tmp_path,capture_output=True,text=True,timeout=15)
    assert about.returncode==0,about.stderr
    assert json.loads(about.stdout)['version']=='3.2.0'
    code='''from pathlib import Path
from web_bridge.app import Companion
from web_bridge.resources import UI_ROOT
root=Path('project');root.mkdir()
c=Companion(None,Path('runtime'))
try:
    c.configure(root=str(root.resolve()),read=True,integrations=True)
    assert 'Work precisely' in c.skill_read('web-bridge-project-work',workspace_id=c.workspace_id)['text']
    assert 'Saved work' in (UI_ROOT/'control.html').read_text(encoding='utf-8')
    assert (UI_ROOT/'ui.css').is_file()
finally:c.close()
'''
    result=subprocess.run([sys.executable,'-B','-c',code],cwd=tmp_path,env={**os.environ,'PYTHONPATH':str(extracted/'src')},capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr

def test_web_transport_module_entry_handles_stdio_from_other_directory(tmp_path):
    message={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18'}}
    env={**os.environ,'PYTHONPATH':str(ROOT/'src'),'CTF_TARGETS':'{}','CTF_CONFIG':''}
    result=subprocess.run([sys.executable,'-B','-m','web_bridge.transport','stdio'],input=json.dumps(message)+'\n',cwd=tmp_path,env=env,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['result']['serverInfo']['name']=='ctf-instance-bridge'
