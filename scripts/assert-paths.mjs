import assert from 'node:assert/strict';
import {readdirSync} from 'node:fs';
import {join} from 'node:path';

export function assertSourcePaths(root, paths, tracked = []) {
  const recorded = new Map(tracked.map(path => [path.toLowerCase(), path]));
  for (const path of paths) {
    let directory = root;
    for (const part of path.split('/')) {
      assert.ok(readdirSync(directory).includes(part), `Missing source or incorrect case: ${path}`);
      directory = join(directory, part);
    }
    const gitPath = recorded.get(path.toLowerCase());
    assert.ok(!gitPath || gitPath === path, `Git records ${gitPath}, but the build expects ${path}. Match the tracked spelling.`);
  }
}
