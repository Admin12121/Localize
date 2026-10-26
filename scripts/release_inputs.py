"""Deterministic, curated release inputs; generated code and private runtime stay out."""
import json
from pathlib import Path
import re
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'src/web_bridge'
OUT=ROOT/'dist/release'
TEXT={'.py','.mjs','.js','.ts','.json','.html','.css','.ps1','.sh','.txt','.toml','.yml','.yaml','.md'}
EXCLUDED={'__pycache__','.pytest_cache','.runtime','node_modules','dist','outputs','.git'}

def clean_bytes(path):
    data=path.read_bytes()
    return data.replace(b'\r\n',b'\n') if path.suffix in TEXT else data

def files_under(root):
    for path in sorted(root.rglob('*')):
        if path.is_file() and not path.is_symlink() and not any(p in EXCLUDED for p in path.relative_to(root).parts) and path.suffix in TEXT:
            if path.name not in ('targets.json',) and not path.name.startswith('.env'):
                yield path

def portable_readme():
    text=(ROOT/'README.md').read_text(encoding='utf-8')
    return re.sub(r'^!\[[^\]]*\]\([^\n]+\)\n','',text,flags=re.M).encode('utf-8')

def source_payload():
    entries={}
    for folder in ('src','gateway','plugin','scripts','tests','.github','requirements'):
        for path in files_under(ROOT/folder):entries[path.relative_to(ROOT).as_posix()]=clean_bytes(path)
    for name in ('package.json','package-lock.json','pyproject.toml','LICENSE','.gitignore','drizzle.config.ts'):
        entries[name]=clean_bytes(ROOT/name)
    entries['README.md']=portable_readme()
    manifest=json.loads((ROOT/'.openai/hosting.json').read_text(encoding='utf-8'));manifest.pop('project_id',None)
    entries['.openai/hosting.json']=(json.dumps(manifest,indent=2)+'\n').encode()
    for name,data in entries.items():
        if re.search(rb'appgprj_[0-9a-f]{32}',data):raise ValueError('Account identity in portable source: '+name)
    return entries

def companion_payload():
    entries={p.relative_to(ROOT).as_posix():clean_bytes(p) for p in files_under(PACKAGE)}
    for name in ('scripts/run.py','scripts/start.ps1','scripts/start.sh','requirements/agent.txt','requirements/integrations.txt','LICENSE'):
        entries[name]=clean_bytes(ROOT/name)
    return entries

def write_zip(path,entries,prefix=''):
    path.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(path,'w') as archive:
        for name,data in sorted(entries.items()):
            info=ZipInfo(prefix+name,(2026,10,25,0,0,0));info.compress_type=ZIP_DEFLATED
            info.external_attr=(0o100755 if name.endswith('.sh') else 0o100644)<<16
            archive.writestr(info,data)
