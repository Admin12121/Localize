import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import {execFileSync} from 'node:child_process';
import {assertSourcePaths} from './assert-paths.mjs';


const required = [
  'LICENSE', '.gitignore',
  'scripts/run.py', 'src/web_bridge/BRIDGE_TOOLS.json',
  'src/web_bridge/app.py', 'gateway/runtime.js',
  'scripts/build.mjs', 'scripts/package-setup.py',
  'scripts/package-release.py', 'tests/node/site.test.mjs',
  'Plugin/plugin.json', 'Plugin/.codex-plugin/plugin.json',
  'Plugin/skills/setup-web-bridge/SKILL.md'
];
const tracked = existsSync('.git') ? execFileSync('git', ['ls-files', '-z'], {encoding: 'utf8'}).split('\0').filter(Boolean) : [];
assertSourcePaths(process.cwd(), required, tracked);
const pkg = JSON.parse(readFileSync('package.json', 'utf8'));
const companion = JSON.parse(readFileSync('src/web_bridge/metadata.json', 'utf8'));
const tools = JSON.parse(readFileSync('src/web_bridge/BRIDGE_TOOLS.json', 'utf8'));
assert.equal(pkg.version, companion.version, 'Companion version differs');
assert.equal(pkg.version, tools.bridge_version, 'MCP catalog version differs');
assert.ok(Array.isArray(tools.tools) && tools.tools.length > 0, 'No tools registered');

assert.ok(existsSync('README.md'), 'Missing main README');
console.log(`Source verification succeeded (v${pkg.version}; ${tools.tools.length} MCP tools).`);
