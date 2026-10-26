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
