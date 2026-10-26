"""Run the source checkout or extracted companion without installing it."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from web_bridge.cli import main

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Companion stopped: " + str(exc), file=sys.stderr)
        sys.exit(1)
