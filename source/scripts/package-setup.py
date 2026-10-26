"""Portable installer source: no account IDs, generated builds, runtime state or credentials."""
import json
import re
from pathlib import Path
from zipfile import ZipFile,ZipInfo,ZIP_DEFLATED
out=Path('outputs');out.mkdir(exist_ok=True)
files=[Path(x) for x in ['package.json','package-lock.json','.gitignore','README.md','LICENSE','SECURITY.md','ARCHITECTURE.md','SETUP.md','CONTRIBUTING.md','bridge/README.md','drizzle.config.ts']]
for folder,pattern in [('scripts','*.mjs'),('scripts','*.py'),('worker','*'),('bridge','*'),('bridge/server','*.py'),('bridge/tests','*.py'),('tests','*.mjs'),('db','*.ts'),('drizzle','*.sql'),('drizzle/meta','*.json'),('setup-plugin','plugin.json'),('setup-plugin/.codex-plugin','plugin.json'),('setup-plugin/skills/setup-web-bridge','SKILL.md'),('.github/workflows','*.yml'),('docs','**/*.md')]:
    files.extend(p for p in Path(folder).glob(pattern) if p.is_file() and p.suffix not in ('.zip','.gz','.pyc') and p.name not in ('targets.json','README.md'))
contents={p.as_posix():p.read_bytes().replace(b'\r\n',b'\n') for p in sorted(set(files))}
manifest=json.loads(Path('.openai/hosting.json').read_text(encoding='utf-8'));manifest.pop('project_id',None)
contents['.openai/hosting.json']=(json.dumps(manifest,indent=2)+'\n').encode()
for name,data in contents.items():
    if re.search(rb'appgprj_[0-9a-f]{32}',data):raise ValueError('Account identity must not enter portable source: '+name)
def write(archive,name,data):
    info=ZipInfo(name,(2026,10,25,0,0,0));info.compress_type=ZIP_DEFLATED
    info.external_attr=(0o100755 if name.endswith('.sh') else 0o100644)<<16
    archive.writestr(info,data)
with ZipFile(out/'web-bridge-portable-source.zip','w') as archive:
    for name,data in contents.items():write(archive,'web-bridge-source/'+name,data)
with ZipFile(out/'web-bridge-setup-plugin.zip','w') as archive:
    for path in [Path('setup-plugin/plugin.json'),Path('setup-plugin/.codex-plugin/plugin.json'),Path('setup-plugin/skills/setup-web-bridge/SKILL.md')]:write(archive,str(path.relative_to('setup-plugin')).replace('\\','/'),path.read_bytes())
    write(archive,'LICENSE',Path('LICENSE').read_bytes())
    for name,data in contents.items():write(archive,'skills/setup-web-bridge/source/'+name,data)
print('Packaged reusable setup plugin and portable source without account identity or runtime state.')
