"""Build portable source and setup plugin without generated copies or secrets."""

from release_inputs import ROOT, OUT, clean_bytes, source_payload, write_zip

source = source_payload()
write_zip(OUT / "web-bridge-portable-source.zip", source, "web-bridge-source/")
plugin = {
    p.relative_to(ROOT / "Plugin").as_posix(): clean_bytes(p)
    for p in (
        ROOT / "Plugin/plugin.json",
        ROOT / "Plugin/.codex-plugin/plugin.json",
        ROOT / "Plugin/skills/setup-web-bridge/SKILL.md",
    )
}
plugin["LICENSE"] = clean_bytes(ROOT / "LICENSE")
plugin.update(
    {"skills/setup-web-bridge/source/" + name: data for name, data in source.items()}
)
write_zip(OUT / "web-bridge-setup-plugin.zip", plugin)
print("Packaged setup plugin and sanitized portable source.")
