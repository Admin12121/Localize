"""Public project attribution, shared by launcher and status responses."""
import json
from pathlib import Path
PROJECT=json.loads((Path(__file__).resolve().parents[1]/'metadata.json').read_text(encoding='utf-8'))
VERSION=PROJECT['version']
