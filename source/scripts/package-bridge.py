"""Deterministic, secret-free cross-platform companion download."""
from pathlib import Path
from zipfile import ZipFile,ZipInfo,ZIP_DEFLATED
root=Path('bridge');out=Path('outputs');out.mkdir(exist_ok=True)
files=[root/name for name in ['metadata.json','launch.py','start.ps1','start.sh','control.html','ui.css','configure-targets.py','example.targets.json','BRIDGE_TOOLS.json','README.md']]+sorted((root/'server').glob('*.py'))+sorted(root.glob('requirements-*.txt'))+sorted(root.glob('skills/*/SKILL.md'))
with ZipFile(out/'web-bridge-companion.zip','w',ZIP_DEFLATED) as archive:
    for file in files:
        info=ZipInfo('web-bridge-companion/'+str(file.relative_to(root)).replace('\\','/'),(2026,10,25,0,0,0))
        info.compress_type=ZIP_DEFLATED
        info.external_attr=(0o100755 if file.suffix=='.sh' or file.name=='configure-targets.py' else 0o100644)<<16
        archive.writestr(info,file.read_bytes().replace(b'\r\n',b'\n'))
    info=ZipInfo('web-bridge-companion/LICENSE',(2026,10,25,0,0,0));info.compress_type=ZIP_DEFLATED;info.external_attr=0o100644<<16
    archive.writestr(info,Path('LICENSE').read_bytes())
print('Packaged cross-platform companion without runtime secrets.')

# zipapp: curated payload runnable without manual extraction.
with ZipFile(out/'Web-Bridge.pyz','w',ZIP_DEFLATED) as archive:
    def write_bundle(name,data):
        info=ZipInfo(name,(2026,10,25,0,0,0));info.compress_type=ZIP_DEFLATED;info.external_attr=0o100644<<16
        archive.writestr(info,data)
    write_bundle('app/LICENSE',Path('LICENSE').read_bytes())
    write_bundle('__main__.py',(root/'bundle-entry.py').read_bytes().replace(b'\r\n',b'\n'))
    for file in files:
        write_bundle('app/'+file.relative_to(root).as_posix(),file.read_bytes().replace(b'\r\n',b'\n'))
print('Packaged single-file Web-Bridge.pyz (Python 3.10+).')
