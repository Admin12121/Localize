import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync, readFileSync} from 'node:fs';
import {join} from 'node:path';


const json = path => JSON.parse(readFileSync(path, 'utf8'));

test('the published bridge version agrees across source metadata', () => {
  const app = json('package.json');
  const companion = json('src/web_bridge/metadata.json');
  const catalog = json('src/web_bridge/BRIDGE_TOOLS.json');
  assert.equal(companion.version, app.version);
  assert.equal(catalog.bridge_version, app.version);
  assert.ok(catalog.tools.length > 0);
});

test('source and distribution dependencies exist', () => {
  for (const file of [
    'LICENSE', 'scripts/release_inputs.py',
    'scripts/bundle-entry.py', 'scripts/package-setup.py',
    'Plugin/skills/setup-web-bridge/SKILL.md',
  ]) {
    assert.ok(existsSync(join(process.cwd(), file)), `Missing repository source: ${file}`);
  }
  assert.ok(existsSync('README.md'), 'Missing main README');
});

test('release version remains consistent across installers, metadata, gateway, and CI', () => {
  const version = json('package.json').version;
  const plugin = json('Plugin/plugin.json');
  const codexPlugin = json('Plugin/.codex-plugin/plugin.json');
  assert.equal(plugin.version, codexPlugin.version);
  assert.match(readFileSync('README.md', 'utf8'), new RegExp('Version \\*\\*' + version.replaceAll('.', '\\.') ));
  assert.match(readFileSync('pyproject.toml', 'utf8'), new RegExp('version = "' + version.replaceAll('.', '\\.') + '"'));
  const lock = json('package-lock.json');
  assert.equal(lock.version, version);
  assert.equal(lock.packages[''].version, version);
  const files = [
    'scripts/install.ps1', 'scripts/install.sh', 'gateway/runtime.js',
    'gateway/interface.html', '.github/workflows/ci.yml',
    'src/web_bridge/ui/control.html',
  ];
  for (const path of files) {
    const text = readFileSync(path, 'utf8');
    assert(text.includes(version), path + ' does not reference current ' + version);
    for (const old of ['3.2.0', '3.2.1', '3.2.2']) {
      assert(!text.includes(old), path + ' references outdated Localize ' + old);
    }
  }
  const installUrl = 'releases/download/v' + version;
  for (const path of ['scripts/install.ps1', 'scripts/install.sh', 'README.md']) {
    assert(readFileSync(path, 'utf8').includes(installUrl), path + ' uses an old release URL');
  }
});
