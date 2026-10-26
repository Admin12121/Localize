"""The package owns its UI, skill resources, metadata and tool contract."""

import json
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
UI_ROOT = PACKAGE_ROOT / "ui"
PROJECT = json.loads((PACKAGE_ROOT / "metadata.json").read_text(encoding="utf-8"))
VERSION = PROJECT["version"]
TOOL_DEFINITIONS = json.loads(
    (PACKAGE_ROOT / "BRIDGE_TOOLS.json").read_text(encoding="utf-8")
)["tools"]
