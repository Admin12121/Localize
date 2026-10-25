import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync, readFileSync} from 'node:fs';
import {join} from 'node:path';

const json = path => JSON.parse(readFileSync(path, 'utf8'));

test('the published bridge version agrees across source metadata', () => {
  const app = json('package.json');
  const companion = json('bridge/metadata.json');
  const catalog = json('bridge/BRIDGE_TOOLS.json');
  assert.equal(companion.version, app.version);
  assert.equal(catalog.bridge_version, app.version);
  assert.ok(catalog.tools.length > 0);
});

test('source and distribution documentation dependencies exist', () => {
  for (const file of [
    'README.md', 'SECURITY.md', 'LICENSE',
    'bridge/bundle-entry.py', 'scripts/package-setup.py',
    'setup-plugin/skills/setup-web-bridge/SKILL.md',
  ]) {
    assert.ok(existsSync(join(process.cwd(), file)), `Missing repository source: ${file}`);
  }
});
