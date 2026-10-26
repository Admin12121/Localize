# Releasing Localize

The release workflow at `.github/workflows/release.yml` runs the complete Python and Node suites on **Windows, macOS and Ubuntu**. It publishes the wheel, shell installers, companion bundles, setup plugin and SHA-256 checksums only if every platform passes. It also checks that the Git tag matches the package version.

## Before tagging

1. Verify all `3.2.1` versions agree in `package.json`, `pyproject.toml`, `src/web_bridge/metadata.json`, `src/web_bridge/BRIDGE_TOOLS.json`, and both installer scripts.
2. Check the bundled SVG artwork can legally be redistributed. The exact supplied SVG is in `src/web_bridge/ui/scene-original.svg`; don't publish it under MIT unless the author/license permits that distribution.
3. Test locally from the repository root:

   ```powershell
   npm ci
   npm run build
   npm run validate
   npm test
   uv run --with pytest --with build -- python -m pytest -q tests/python
   uv run --with build -- python -m build --wheel --outdir dist/release
   uv run python scripts/package-release.py
   ```

4. Review `git status`, commit the changes and push the source branch:

   ```powershell
   git add .
   git commit -m "Release Localize v3.2.1"
   git push origin main
   ```

5. After the normal CI run passes on all three OS runners, create/push an annotated release tag:

   ```powershell
   git tag -a v3.2.1 -m "Localize v3.2.1"
   git push origin v3.2.1
   ```

The tag starts the `Release` GitHub Actions workflow. Its publish job creates a GitHub Release automatically at `https://github.com/Admin12121/Localize/releases/tag/v3.2.1`.

If repository Actions cannot publish, check **Settings → Actions → General → Workflow permissions** to allow workflow token write access. Do not bypass failing test jobs or manually attach artifacts from an unverified build.

## How existing users update

Stop the running companion. The same platform-specific installer used originally can be run again to replace the wheel with the current release. Restart `localizeit`; check `localizeit --about` and `/overview` in the local dashboard. Runtime config survives a tool update.

Updating the local companion does **not** replace the account-owned private Site. The existing Site and plugin can continue using the unchanged 27-tool contract. If the owner wants to refresh the Site gateway/bundled download, update their *existing* private Site from the new setup ZIP, preserving identity, database and secrets.

## How new users install

Install the companion using the verified `install.ps1` or `install.sh` asset. New users then follow README's private-Site and generated ChatGPT-plugin instructions. The ZIP is *setup source*, not a standalone one-click ChatGPT plugin installation.

## Rollback

Re-run the previous trusted release installer (e.g., `v3.2.0`) to restore its wheel. Do not delete the per-user runtime directory. Revert any private Site deployment separately using its original Site ownership/workflow. Back up local settings before changing release versions.
