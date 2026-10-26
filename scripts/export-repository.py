"""Create a clean GitHub-ready source directory without touching the running bridge."""

import argparse
import shutil
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--destination",
        type=Path,
        default=ROOT / "dist" / "exports" / "github-repository",
    )
    args = parser.parse_args()
    destination = args.destination.resolve()
    if (
        destination == ROOT
        or ROOT in destination.parents
        and destination.parts[: len(ROOT.parts) + 1] != (*ROOT.parts, "dist")
    ):
        raise SystemExit("Destination must not overwrite the source tree.")
    if destination.exists():
        raise SystemExit(
            "Destination already exists. Export to an empty path; no files were overwritten."
        )
    # Canonical curated source, not extracted Companion/, Plugin/ or local runtime state.
    import subprocess

    subprocess.run(
        [
            "python" if __import__("sys").platform == "win32" else "python3",
            "scripts/package-setup.py",
        ],
        cwd=ROOT,
        check=True,
    )
    archive = ROOT / "dist/release" / "web-bridge-portable-source.zip"
    destination.mkdir(parents=True, exist_ok=False)
    try:
        with ZipFile(archive) as bundle:
            for member in bundle.infolist():
                file = Path(member.filename)
                if not file.parts or file.parts[0] != "web-bridge-source":
                    raise ValueError("Unexpected source archive member")
                relative = Path(*file.parts[1:])
                if not relative.parts:
                    continue
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("Unsafe archive member")
                target = destination / relative
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(bundle.read(member))
        print("Exported GitHub-ready source to:", destination)
        print("Source files:", sum(f.is_file() for f in destination.rglob("*")))
    except Exception:
        shutil.rmtree(destination)
        raise


if __name__ == "__main__":
    main()
