# Set up Web-Bridge in another account

Created by **admin12121** · MIT.

## Recipient checklist

1. Use your own ChatGPT account with Sites, plugin creation, and build/file tools available. Workspace administrators may restrict them.
2. Attach `Web-Bridge-Setup-Plugin.zip` to a build-capable Sites chat. Ask to install the package and create your private Site; the exact reusable prompt is in README.md. Where ZIP import is supported, import it and invoke Web-Bridge Setup explicitly.
3. The setup workflow copies sanitized source, creates a new private Site, generates a new encryption secret, builds and publishes, and returns your Site-generated plugin. Installing the package alone does not perform these steps.
4. Download and run `Web-Bridge.pyz` on your computer. Windows: `python Web-Bridge.pyz`; macOS/Linux: `python3 Web-Bridge.pyz`. Python 3.10+ and official cloudflared are prerequisites.
5. Choose permissions locally, then save the printed Site endpoint and key in your private Site. Never send credentials through chat.
6. In a new normal Chat, select your canonical plugin and verify `bridge_status`, then one approved operation.

If a required capability is unavailable, stop and explain the missing capability. Do not reuse someone else's private Site as a workaround. Universal availability across accounts is not guaranteed.

## Existing installation

Stop the companion with Ctrl+C. Replace only its bundle file. To retain a ZIP installation's key, run the new bundle from the old folder using `python Web-Bridge.pyz --runtime .runtime` (python3 on macOS/Linux). Permissions must be selected again. Update the Site endpoint after a Quick Tunnel restart; leave the key blank to retain the saved key when unchanged.

## Source and privacy

Use `outputs/web-bridge-portable-source.zip` for a clean new-account or GitHub source copy. Its hosting manifest excludes the original project ID. It contains no local runtime directory or credentials. Fresh deployments need a new encryption secret and owner-private access. Preserve the original identity, secret, and database only when explicitly upgrading an existing deployment you own.
