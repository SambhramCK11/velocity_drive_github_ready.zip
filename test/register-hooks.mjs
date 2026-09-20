/** Installs the .html text-module loader. Used via `node --import`. */
import { register } from 'node:module';

register('./html-hooks.mjs', import.meta.url);
