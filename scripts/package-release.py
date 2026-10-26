"""Prepare public GitHub source and release assets from the sanitized build outputs."""

from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
import hashlib
import shutil
from release_inputs import ROOT, OUT, portable_readme

out = OUT
required = [
    "Web-Bridge.pyz",
    "web-bridge-companion.zip",
    "web-bridge-setup-plugin.zip",
    "web-bridge-portable-source.zip",
]
if any(not (out / name).is_file() for name in required):
    raise SystemExit("Run node scripts/build.mjs first.")
shutil.copyfile(
    out / "web-bridge-portable-source.zip", out / "Web-Bridge-GitHub-Source.zip"
)
assets = {
    "Web-Bridge.pyz": (out / "Web-Bridge.pyz").read_bytes(),
    "web-bridge-companion.zip": (out / "web-bridge-companion.zip").read_bytes(),
    "web-bridge-setup-plugin.zip": (out / "web-bridge-setup-plugin.zip").read_bytes(),
    "Web-Bridge-GitHub-Source.zip": (out / "Web-Bridge-GitHub-Source.zip").read_bytes(),
    "LICENSE": Path("LICENSE").read_bytes(),
    "install.ps1": (ROOT / "scripts/install.ps1").read_bytes().replace(b"\r\n", b"\n"),
    "install.sh": (ROOT / "scripts/install.sh").read_bytes().replace(b"\r\n", b"\n"),
    "README.md": portable_readme(),
}
# Include the installable CLI wheel when built; standalone bundle remains available.
import json

version = json.loads(
    (ROOT / "src/web_bridge/metadata.json").read_text(encoding="utf-8")
)["version"]
wheel = out / f"localizeit-{version}-py3-none-any.whl"
if wheel.is_file():
    assets[wheel.name] = wheel.read_bytes()
# Publish the exact bytes that the manifest and combined archive describe.
for name, data in assets.items():
    (out / name).write_bytes(data)

checksums = "".join(
    hashlib.sha256(data).hexdigest() + "  " + name + "\n"
    for name, data in sorted(assets.items())
)
(out / "SHA256SUMS").write_text(checksums, encoding="utf-8", newline="\n")
assets["SHA256SUMS"] = checksums.encode()
with ZipFile(out / "Web-Bridge-Open-Source-Release.zip", "w") as archive:
    for name, data in sorted(assets.items()):
        info = ZipInfo("Web-Bridge-Release/" + name, (2026, 10, 25, 0, 0, 0))
        info.compress_type = ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        archive.writestr(info, data)
print("Prepared GitHub source, MIT release package, and SHA256SUMS.")
