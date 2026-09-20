/**
 * Node loader hooks that make `import x from './t.html'` return the file's
 * text, which is what Wrangler's default Text module rule does when bundling.
 *
 * Without this, any test that imports worker/index.mjs fails on
 * ERR_UNKNOWN_FILE_EXTENSION, because Node has no built-in text-module loader.
 */

import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

export async function load(url, context, nextLoad) {
  if (url.endsWith('.html')) {
    const source = await readFile(fileURLToPath(url), 'utf8');
    return {
      format: 'module',
      shortCircuit: true,
      source: `export default ${JSON.stringify(source)};`,
    };
  }
  return nextLoad(url, context);
}
