"""Public package and source-entry behavior, independent of an editable install."""
from pathlib import Path
import json
import os
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]

def test_source_entry_reports_version_without_starting_services(tmp_path):
    result=subprocess.run([sys.executable,str(ROOT/'scripts/run.py'),'--about'],cwd=tmp_path,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['version']=='3.2.2'
    assert list(tmp_path.iterdir())==[]

def test_package_imports_and_authorized_workspace_rpc_from_other_directory(tmp_path):
    code='''
import json, pathlib, pkgutil, importlib, sys
sys.path.insert(0,sys.argv[1])
import web_bridge
for module in pkgutil.walk_packages(web_bridge.__path__,web_bridge.__name__+'.'):
    importlib.import_module(module.name)
from web_bridge.app import Companion
from web_bridge.transport.rpc import rpc
root=pathlib.Path(sys.argv[2]);root.mkdir()
(root/'proof.txt').write_text('preserved')
c=Companion(None,pathlib.Path(sys.argv[3]))
try:
    c.configure(root=str(root),read=True,integrations=True)
    response=rpc({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'workspace_read','arguments':{'path':'proof.txt','workspace_id':c.workspace_id}}},c)
    assert response['result']['isError'] is False,response
    assert json.loads(response['result']['content'][0]['text'])['text']=='preserved'
    assert 'Work precisely' in c.skill_read('web-bridge-project-work',workspace_id=c.workspace_id)['text']
finally:c.close()
'''
    result=subprocess.run([sys.executable,'-I','-B','-c',code,str(ROOT/'src'),str(tmp_path/'project'),str(tmp_path/'runtime')],cwd=tmp_path,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
