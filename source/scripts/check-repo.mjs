import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const required = [
  'README.md', 'SECURITY.md', 'LICENSE', '.gitignore',
  'bridge/launch.py', 'bridge/BRIDGE_TOOLS.json',
  'bridge/server/companion.py', 'worker/runtime.js',
  'scripts/build.mjs', 'scripts/package-setup.py',
  'scripts/package-release.py', 'tests/site.test.mjs',
  'setup-plugin/skills/setup-web-bridge/SKILL.md'
];
for (const file of required) assert.ok(existsSync(join(process.cwd(), file)), `Missing source: ${file}`);
const pkg = JSON.parse(readFileSync('package.json', 'utf8'));
const companion = JSON.parse(readFileSync('bridge/metadata.json', 'utf8'));
const tools = JSON.parse(readFileSync('bridge/BRIDGE_TOOLS.json', 'utf8'));
assert.equal(pkg.version, companion.version, 'Companion version differs');
assert.equal(pkg.version, tools.bridge_version, 'MCP catalog version differs');
assert.ok(Array.isArray(tools.tools) && tools.tools.length > 0, 'No tools registered');

const packaging = readFileSync('scripts/package-setup.py', 'utf8');
for (const file of ['SECURITY.md', 'README.md']) {
  assert.ok(packaging.includes("'" + file + "'"), `Packaging omits ${file}`);
}
console.log(`Source verification succeeded (v${pkg.version}; ${tools.tools.length} MCP tools).`);
