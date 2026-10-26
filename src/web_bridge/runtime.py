"""Persistent per-user runtime, independent of source and release extraction."""

import os
import sys
from pathlib import Path


def runtime_home():
    if sys.platform == "win32":
        return (
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
            / "Web-Bridge"
            / "runtime"
        )
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Web-Bridge/runtime"
    return (
        Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
        / "web-bridge"
    )
