"""Locate the single maintained README in a checkout or portable source."""
from pathlib import Path
import re

def readme_path():
    root=Path(__file__).resolve().parents[1]
    for directory in (root,*root.parents):
        candidate=directory/'README.md'
        if candidate.is_file():return candidate
    raise FileNotFoundError('Missing main README.md')

def portable_readme():
    # Illustrations remain in the repository, outside the embedded gateway payload.
    text=readme_path().read_text(encoding='utf-8')
    text=re.sub(r'^!\[[^\]]*\]\([^\n]+\)\n','',text,flags=re.M)
    return text.replace('](source/','](').encode('utf-8')
