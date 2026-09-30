#!/usr/bin/env node
/* valjsx.js — validate FORGE REI OS .jsx files before deploy.
 *
 * The UI has NO build step: every .jsx is Babel-transformed in the browser at load. So a
 * syntax error or a computed JSX tag (`<Icons[x] />`) doesn't fail a build — it white-screens
 * the live dashboard AFTER deploy. This is the gate that catches it on the Mac first.
 *
 * Two checks per file:
 *   1. Real @babel/standalone transform (preset react) — catches any JSX/JS syntax error.
 *   2. Computed-tag scan — `<Something[...]` / `<{...}` in JSX position white-screens even
 *      though it parses; CLAUDE.md bans it ("resolve first: const Ico = Icons[x]||...").
 *
 * Babel is self-bootstrapped: downloaded ONCE to deploy/.cache/ (git-ignored), then reused
 * offline. No node_modules, no committed 2MB blob. Deterministic after the first run.
 *
 * Usage:  node deploy/valjsx.js file1.jsx file2.jsx ...
 * Exit 0 = all clean; exit 1 = at least one failure (message on stderr).
 */
'use strict';
const fs = require('fs');
const path = require('path');
const https = require('https');

const BABEL_VERSION = '7.26.4';
const BABEL_URL = `https://unpkg.com/@babel/standalone@${BABEL_VERSION}/babel.min.js`;
const CACHE_DIR = path.join(__dirname, '.cache');
const CACHE_FILE = path.join(CACHE_DIR, `babel-standalone-${BABEL_VERSION}.js`);

function download(url, dest) {
  return new Promise((resolve, reject) => {
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    const tmp = dest + '.tmp';
    const f = fs.createWriteStream(tmp);
    https.get(url, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        f.close(); fs.rmSync(tmp, { force: true });
        return download(res.headers.location, dest).then(resolve, reject);
      }
      if (res.statusCode !== 200) {
        f.close(); fs.rmSync(tmp, { force: true });
        return reject(new Error(`download ${url} -> HTTP ${res.statusCode}`));
      }
      res.pipe(f);
      f.on('finish', () => f.close(() => { fs.renameSync(tmp, dest); resolve(dest); }));
    }).on('error', (e) => { f.close(); fs.rmSync(tmp, { force: true }); reject(e); });
  });
}

async function loadBabel() {
  if (!fs.existsSync(CACHE_FILE)) {
    process.stderr.write(`valjsx: fetching @babel/standalone@${BABEL_VERSION} (one-time)...\n`);
    await download(BABEL_URL, CACHE_FILE);
  }
  // @babel/standalone assigns `Babel` onto the module/global; require() runs it in this ctx.
  const mod = require(CACHE_FILE);
  return mod && mod.transform ? mod : global.Babel;
}

// Flag a `<` immediately followed by a member/computed/interpolated tag name.
const COMPUTED_TAG = /<\s*[A-Za-z_$][\w$]*\s*\[|<\s*\{/;

async function main() {
  const files = process.argv.slice(2);
  if (!files.length) { process.stderr.write('usage: node valjsx.js <file.jsx> ...\n'); process.exit(2); }
  let Babel;
  try { Babel = await loadBabel(); }
  catch (e) { process.stderr.write(`valjsx: could not load Babel: ${e.message}\n`); process.exit(3); }

  let failed = 0;
  for (const file of files) {
    let src;
    try { src = fs.readFileSync(file, 'utf8'); }
    catch (e) { process.stderr.write(`FAIL ${file}: ${e.message}\n`); failed++; continue; }

    try {
      Babel.transform(src, { presets: ['react'], filename: file });
    } catch (e) {
      process.stderr.write(`FAIL ${file}: ${String(e.message).split('\n')[0]}\n`);
      failed++; continue;
    }

    const lines = src.split('\n');
    let computedHit = -1;
    for (let i = 0; i < lines.length; i++) {
      if (COMPUTED_TAG.test(lines[i])) { computedHit = i + 1; break; }
    }
    if (computedHit > 0) {
      process.stderr.write(
        `FAIL ${file}:${computedHit}: computed JSX tag — resolve first ` +
        `(const Ico = Icons[x] || Icons.Bot; then <Ico/>).\n`);
      failed++; continue;
    }
    process.stdout.write(`OK   ${file}\n`);
  }
  process.exit(failed ? 1 : 0);
}

main();
