import http.client
import json
from pathlib import Path
import sys
import threading
from web_bridge.app import Companion
from web_bridge.transport.control import ControlServer

def test_local_control_login_origin_csrf_and_separate_authority(tmp_path):
    companion=Companion(None,tmp_path/'runtime')
    server=ControlServer(companion,'private-local-login-code',port=0)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    def req(path,data=None,cookie='',extra=None):
        conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
        headers={'Content-Type':'application/json','Origin':origin,'Cookie':cookie,**(extra or {})}
        conn.request('POST' if data is not None else 'GET',path,None if data is None else json.dumps(data),headers)
        res=conn.getresponse();status=res.status;hdr=dict(res.getheaders());body=res.read();conn.close()
        return status,hdr,json.loads(body) if body.startswith(b'{') else body
    try:
        for page in ('/', '/overview', '/workspace', '/docker',
                     '/connections', '/activity', '/agent'):
            status, headers, html = req(page)
            assert status == 200
            assert 'text/html' in headers['Content-Type']
            assert b'id="login"' in html and b'id="content" hidden' in html
        assert req('/does-not-exist', cookie='')[0] == 401
        assert req('/assets/scene.svg')[0] == 401
        assert req('/api/state')[0]==401
        assert req('/api/login',{'code':'wrong'})[0]==403
        status,headers,body=req('/api/login',{'code':'private-local-login-code'})
        assert status==200 and body['csrf']
        cookie=headers['Set-Cookie'].split(';')[0]
        status, asset_headers, svg = req('/assets/scene.svg', cookie=cookie)
        assert status == 200
        assert 'image/svg+xml' in asset_headers['Content-Type']
        assert b'viewBox="0 0 1310 1105"' in svg
        assert b'2,087' not in svg and b'Snyk Scan' not in svg
        status,state_headers,state=req('/api/state',cookie=cookie)
        assert status==200
        assert req('/api/state',cookie=cookie,extra={'If-None-Match':state_headers['ETag']})[0]==304
        root=tmp_path/'project';root.mkdir()
        companion.configure(root=str(root),read=True,execution=True,host=True)
        job=companion.command_request([sys.executable,'-c','print(1)'],idempotency_key='local-detail-01',environment='host',workspace_id=companion.bridge_status()['workspace_id'])
        companion.jobs.items[job['job_id']]['output']='bounded-output'
        path='/api/job?id='+job['job_id']
        assert req(path)[0]==401
        assert req(path,cookie=cookie,extra={'Origin':'https://evil.example'})[0]==403
        assert req(path,cookie=cookie)[2]['output']=='bounded-output'
        status,changed_headers,state=req('/api/state',cookie=cookie,extra={'If-None-Match':state_headers['ETag']})
        assert status==200 and 'output' not in state['jobs'][0]
        assert req('/api/job?id=unknown',cookie=cookie)[0]==400
        assert req('/api/pause',{'paused':True},cookie)[0]==403
        assert req('/api/pause',{'paused':True},cookie,{'X-Web-Bridge-CSRF':body['csrf'],'Origin':'https://evil.example'})[0]==403
        assert req('/api/pause',{'paused':True},cookie,{'X-Web-Bridge-CSRF':body['csrf']})[0]==200
        assert companion.paused
        assert req('/mcp',{},cookie,{'X-Web-Bridge-CSRF':body['csrf']})[0]==404
        assert req('/',extra={'Host':'evil.example'})[0]==403
    finally:server.shutdown();server.server_close();companion.close()

def test_cross_platform_launcher_starts_without_a_tunnel(tmp_path):
    import subprocess
    import time
    runtime=tmp_path/'runtime'
    process=subprocess.Popen([sys.executable,str(Path(__file__).resolve().parents[2]/'scripts/run.py'),'--no-browser','--runtime',str(runtime),'--rpc-port','0','--control-port','0'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
    try:
        lines=[]
        for _ in range(8):
            line=process.stdout.readline();lines.append(line)
            if 'Local-only launch' in line:break
            if not line:break
        assert process.poll() is None, process.stderr.read()
        assert any('LOCAL CONTROL PANEL: http://127.0.0.1:' in line for line in lines), process.stderr.read()
        assert (runtime/'site-connection-key').exists()
    finally:
        process.terminate();process.communicate(timeout=8)


def test_single_file_launcher_help_and_local_only_start(tmp_path):
    import subprocess
    bundle=Path(__file__).resolve().parents[2]/'dist/release/Web-Bridge.pyz'
    help_result=subprocess.run([sys.executable,str(bundle),'--help'],capture_output=True,text=True,timeout=10)
    assert help_result.returncode==0 and 'Windows, macOS, Linux' in help_result.stdout
    runtime=tmp_path/'persistent-runtime'
    process=subprocess.Popen([sys.executable,str(bundle),'--local-only','--no-browser','--runtime',str(runtime),'--rpc-port','0','--control-port','0'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
    try:
        lines=[]
        for _ in range(8):
            line=process.stdout.readline();lines.append(line)
            if 'Local-only launch' in line or not line:break
        assert process.poll() is None
        assert any('3.2.3' in line for line in lines)
        assert (runtime/'site-connection-key').is_file()
    finally:process.terminate();process.communicate(timeout=8)

def test_bundle_about_metadata_does_not_start_a_companion(tmp_path):
    import subprocess
    bundle=Path(__file__).resolve().parents[2]/'dist/release/Web-Bridge.pyz'
    runtime=tmp_path/'not-created'
    result=subprocess.run([sys.executable,str(bundle),'--about','--runtime',str(runtime)],capture_output=True,text=True,encoding='utf-8',timeout=10)
    assert result.returncode==0
    metadata=json.loads(result.stdout)
    assert metadata['author']==metadata['creator']=='admin12121'
    assert metadata['license']=='MIT' and metadata['version']=='3.2.3'
    assert not runtime.exists()
    assert Companion(None,tmp_path/'runtime').bridge_status()['creator']=='admin12121'


def test_local_dashboard_focuses_on_one_docker_start_and_separate_views():
    from web_bridge.resources import UI_ROOT
    html = (UI_ROOT/'control.html').read_text(encoding='utf-8')
    for view in ('overview','project','docker','integrations','activity','agent'):
        assert f'id="page-{view}"' in html
        assert f'data-view="{view}"' in html
    assert html.count('id="docker-form"') == 1
    assert html.count('id="docker-start"') == 1
    assert 'Start Docker project' in html
    assert 'dockerProgress(' in html
    assert "action:'pull'" in html
    assert "action:'create'" in html
    assert "action:'start'" in html
    assert "environment:'docker',shell:'sh'" in html
    assert 'id="docker-check"' not in html
    assert 'data-docker-action="pull"' not in html
    assert 'data-docker-action="create"' not in html
    assert html.count('id="profile-environment"') == 1
    assert html.count('id="docker-image"') == 1
    for route, view in (
        ('/overview','overview'), ('/workspace','project'), ('/docker','docker'),
        ('/connections','integrations'), ('/activity','activity'), ('/agent','agent'),
    ):
        assert f'<a href="{route}" data-view="{view}"' in html
    assert "history.pushState" in html
    assert "history.replaceState" in html
    assert "addEventListener('popstate'" in html
    assert "sessionStorage.setItem('localize-view'" not in html
    assert 'data-docker-action="attach"' in html
    assert 'data-docker-action="remove"' in html


def test_original_svg_geometry_is_used_without_example_findings():
    import xml.etree.ElementTree as ET
    from web_bridge.resources import UI_ROOT
    original = (UI_ROOT / 'scene-original.svg').read_text(encoding='utf-8')
    dashboard = (UI_ROOT / 'scene-dashboard.svg').read_text(encoding='utf-8')
    original_root = ET.fromstring(original)
    dashboard_root = ET.fromstring(dashboard)
    assert original_root.get('viewBox') == dashboard_root.get('viewBox') == '0 0 1310 1105'
    def paths(root):
        return [
            element.attrib['d']
            for element in root.iter()
            if element.tag.rsplit('}', 1)[-1] == 'path' and 'd' in element.attrib
        ]
    assert len(paths(original_root)) == 78
    assert len(paths(dashboard_root)) == 78
    assert paths(original_root) == paths(dashboard_root)
    for sample in ('2,087', '1,227', '378', 'Snyk Scan', 'At Risk'):
        assert sample not in dashboard
    from web_bridge.resources import UI_ROOT
    scene_script = (UI_ROOT / 'scene.js').read_text(encoding='utf-8')
    html = (UI_ROOT / 'control.html').read_text(encoding='utf-8')
    assert 'paintScene(s)' in scene_script and 'sceneCounts(s)' in scene_script
    assert '__SCENE_JS__' in html
    assert 'id="bridge-scene"' in html
