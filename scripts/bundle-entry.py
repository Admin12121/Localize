"""Single-file distribution bootstrap with a separate persistent runtime."""

from pathlib import Path
import runpy
import sys
import tempfile
from zipfile import ZipFile


def main():
    args = sys.argv[1:]
    local_only = "--local-only" in args
    args = [a for a in args if a != "--local-only"]
    if not local_only and "--tunnel" not in args:
        args.append("--tunnel")
    with tempfile.TemporaryDirectory(prefix="web-bridge-") as folder:
        with ZipFile(Path(sys.argv[0]).resolve()) as bundle:
            for info in bundle.infolist():
                if not info.filename.startswith("app/") or info.is_dir():
                    continue
                relative = Path(info.filename).relative_to("app")
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("Invalid bundle path.")
                destination = Path(folder) / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(bundle.read(info))
        sys.argv = [str(Path(folder) / "scripts/run.py"), *args]
        runpy.run_path(sys.argv[0], run_name="__main__")


if __name__ == "__main__":
    main()
