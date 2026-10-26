# Localize v3.2.1

Release date: 2026-10-26

A maintenance and usability update to the Localize (Web-Bridge) v3.2 series. This release retains the 27-tool ChatGPT MCP contract and the existing companion runtime format.

## What's changed

- **Focused local dashboard:** Overview, Workspace, Docker, Connections, Activity and Local agent are now URL-addressable local views with Back/Forward support.
- **Streamlined Docker setup:** one guided Start Docker operation handles project configuration, image readiness, container creation/start, verification and command-profile selection. Advanced attach/remove/stop/logging actions remain available separately.
- **Original operational scene:** integrates the exact source SVG paths into Overview, strips example scanner/vulnerability values and displays measured local companion counts. The ring shapes are a *schematic*, not quantitative proportions of live metrics.
- **Release packaging:** SVG and JavaScript scene assets ship in the Python wheel, companion archive and single-file distribution.
- **Regression coverage:** route handling, SVG geometry and bundled UI assets. Node test harness updated to account for the inlined scene controller.

## Upgrade an existing computer

Stop the running companion, then reinstall using the verified release installer.

**Windows PowerShell:**
```powershell
irm https://github.com/Admin12121/Localize/releases/download/v3.2.1/install.ps1 | iex
localizeit --about
localizeit
```

**macOS / Linux:**
```sh
curl -fsSL https://github.com/Admin12121/Localize/releases/download/v3.2.1/install.sh | sh
localizeit --about
localizeit
```

For users who already have uv:
```sh
uv tool install --force --python 3.12 https://github.com/Admin12121/Localize/releases/download/v3.2.1/localizeit-3.2.1-py3-none-any.whl
```

Use `localizeit --local-only` to check the local dashboard without bringing up a tunnel.

## ChatGPT plugin / private Site

- **Existing users:** retain your existing private Site and canonical plugin. The tool contract has not changed, so replacing the local companion does not require a replacement Site.
- **Optional Site refresh:** attach the new `web-bridge-setup-plugin.zip` to the original Site builder, upgrade the *same* Site, and preserve connection records/secrets. This updates gateway assets and bundled downloads.
- **New users:** install the Localize companion; separately create their own private Site with the setup archive and a Sites-enabled environment. Installing the archive alone does not deploy a private Site.

## Verification requirements

Before making this release public, run `npm ci`, `npm run build`, `npm run validate`, `npm test`, and the full Python suite on supported OS runners. Build the wheel before `python scripts/package-release.py` and verify the `SHA256SUMS` assets.

**Note on design assets:** Confirm the legal right to redistribute the supplied exact SVG source and its derived dashboard version under the repository's license before publishing an open-source release.
