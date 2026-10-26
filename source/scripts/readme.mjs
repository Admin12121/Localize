import {existsSync} from 'node:fs';
import {dirname,join,resolve} from 'node:path';

export function readmePath(root=process.cwd()) {
  let directory=resolve(root);
  while (true) {
    const candidate=join(directory,'README.md');
    if (existsSync(candidate)) return candidate;
    const parent=dirname(directory);
    if (parent===directory) throw new Error('Missing main README.md');
    directory=parent;
  }
}
