import hashlib
from io import BytesIO
import json
from pathlib import Path
import tarfile
import pytest

from web_bridge.setup import launcher, tunnel

ASSET='cloudflared-linux-amd64'
URL='https://github.com/cloudflare/cloudflared/releases/download/2026.10.4/'+ASSET

class Response(BytesIO):
    def __init__(self,data,url):super().__init__(data);self.url=url
    def geturl(self):return self.url

def downloads(payload,asset=ASSET,digest=None,url=None):
    url=url or 'https://github.com/cloudflare/cloudflared/releases/download/2026.10.4/'+asset
    metadata={'tag_name':'2026.10.4','assets':[{'name':asset,'size':len(payload),'digest':digest or 'sha256:'+hashlib.sha256(payload).hexdigest(),'browser_download_url':url}]}
    requests=[]
    def open_url(request,timeout):
        address=request.full_url;requests.append(address)
        return Response(json.dumps(metadata).encode() if address==tunnel.RELEASE_URL else payload,address)
    return open_url,requests

@pytest.mark.parametrize('system,machine,expected',[
    ('Windows','AMD64','cloudflared-windows-amd64.exe'),
    ('Linux','x86_64','cloudflared-linux-amd64'),
    ('Linux','aarch64','cloudflared-linux-arm64'),
    ('Darwin','x86_64','cloudflared-darwin-amd64.tgz'),
    ('Darwin','arm64','cloudflared-darwin-arm64.tgz'),
])
def test_platform_selects_official_native_asset(system,machine,expected):
    assert tunnel.asset_name(system,machine)==expected

def test_download_is_verified_and_cache_reused_without_network(tmp_path):
    open_url,requests=downloads(b'fixture executable')
    path=tunnel.ensure_cloudflared(tmp_path/'cache',system='Linux',machine='x86_64',opener=open_url,report=lambda message:None)
    assert path.read_bytes()==b'fixture executable' and len(requests)==2
    def forbidden(*args,**kwargs):pytest.fail('Verified cache triggered another download.')
    assert tunnel.ensure_cloudflared(tmp_path/'cache',system='Linux',machine='x86_64',opener=forbidden,report=lambda message:None)==path
    path.write_bytes(b'tampered')
    assert tunnel.cached_cloudflared(tmp_path/'cache',system='Linux',machine='x86_64') is None

def test_checksum_mismatch_never_installs_executable(tmp_path):
    open_url,_=downloads(b'unverified',digest='sha256:'+'0'*64)
    with pytest.raises(tunnel.SetupError,match='checksum'):
        tunnel.ensure_cloudflared(tmp_path/'cache',system='Linux',machine='x86_64',opener=open_url,report=lambda message:None)
    assert not (tmp_path/'cache/cloudflared').exists()

def test_non_official_download_is_rejected_before_fetch(tmp_path):
    open_url,requests=downloads(b'bad',url='https://unconfigured.invalid/tunnel')
    with pytest.raises(tunnel.SetupError,match='official'):
        tunnel.ensure_cloudflared(tmp_path/'cache',system='Linux',machine='x86_64',opener=open_url,report=lambda message:None)
    assert len(requests)==1

@pytest.mark.parametrize('name',['cloudflared','../cloudflared'])
def test_macos_extracts_only_expected_regular_binary(tmp_path,name):
    data=BytesIO()
    with tarfile.open(fileobj=data,mode='w:gz') as archive:
        member=tarfile.TarInfo(name);member.size=6;archive.addfile(member,BytesIO(b'binary'))
    open_url,_=downloads(data.getvalue(),asset='cloudflared-darwin-arm64.tgz')
    if name.startswith('..'):
        with pytest.raises(tunnel.SetupError,match='archive'):
            tunnel.ensure_cloudflared(tmp_path/'cache',system='Darwin',machine='arm64',opener=open_url,report=lambda message:None)
        assert not (tmp_path/'cloudflared').exists()
    else:
        result=tunnel.ensure_cloudflared(tmp_path/'cache',system='Darwin',machine='arm64',opener=open_url,report=lambda message:None)
        assert result.read_bytes()==b'binary'

def test_local_and_information_commands_never_download(tmp_path,monkeypatch,capsys):
    monkeypatch.setattr(launcher,'ensure_cloudflared',lambda:pytest.fail('Unexpected download'))
    launcher.main(['--about']);assert json.loads(capsys.readouterr().out)['version']=='3.2.2'
    calls=[];monkeypatch.setattr(launcher.cli,'main',lambda args,**kwargs:calls.append((args,kwargs)))
    launcher.main(['--local-only'])
    assert '--tunnel' not in calls[0][0] and calls[0][1]=={}

def test_default_launcher_prepares_tunnel_then_uses_existing_authority(tmp_path,monkeypatch):
    executable=tmp_path/'cloudflared';executable.write_text('fixture')
    monkeypatch.setattr(launcher.cli,'find_cloudflared',lambda:None)
    monkeypatch.setattr(launcher,'ensure_cloudflared',lambda:executable)
    calls=[];monkeypatch.setattr(launcher.cli,'main',lambda args,**kwargs:calls.append((args,kwargs)))
    launcher.main(['--no-browser'])
    assert '--tunnel' in calls[0][0] and calls[0][1]['tunnel_binary']==executable
