import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, mkdirSync, writeFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join, resolve, sep} from 'node:path';
import {assertSourcePaths} from '../../scripts/assert-paths.mjs';

function fixture(name, run) {
  const root = mkdtempSync(join(tmpdir(), 'web-bridge-paths-'));
  try {
    mkdirSync(join(root, name));
    writeFileSync(join(root, name, 'plugin.json'), '{}');
    run(root);
  } finally {
    assert.ok(resolve(root).startsWith(resolve(tmpdir()) + sep));
    rmSync(root, {recursive: true, force: true});
  }
}

test('build paths reject case aliases even on case-insensitive filesystems', () => {
  fixture('Plugin', root => {
    assertSourcePaths(root, ['Plugin/plugin.json']);
    assert.throws(() => assertSourcePaths(root, ['plugin/plugin.json']), /incorrect case/);
  });
});

test('build paths reject a working-tree rename absent from Git metadata', () => {
  fixture('plugin', root => {
    assert.throws(() => assertSourcePaths(root, ['plugin/plugin.json'], ['Plugin/plugin.json']), /Git records Plugin/);
  });
});
