#!/usr/bin/env node
// get-shopify-token.mjs — mint a durable Shopify Admin API token for Everaly.
//
// Node twin of get_shopify_token.py, for machines with Node but no Python
// (the Windows workstation). Same flow, same output, no dependencies.
//
// Why this exists: Everaly has no legacy "custom app" flow, so there is no
// `shpat_` token to reveal in the admin. A Dev Dashboard app exposes only a
// Client ID, a Secret, and a CI/CD automation token (`atkn_`) — none of which
// authenticate against /admin/api. The supported path is a one-time OAuth
// authorization-code exchange, which returns an OFFLINE token that does not
// expire. That is what SHOPIFY_ADMIN_TOKEN wants.
//
// The secret comes from an env var or a hidden prompt, never from argv. The
// token is written straight into dropship.env and never printed.
//
// --- Before running, in the Dev Dashboard for your app ---
//   1. Configuration -> Admin API access scopes, tick:
//        read_products, read_inventory, read_orders,
//        read_fulfillments, read_customers, read_locations
//   2. Configuration -> Redirect URLs, add exactly:
//        http://localhost:3456/callback
//   3. Release a new version so the config goes live.
//   4. Settings -> copy the Client ID, reveal the Secret.
//
// --- Run ---
//   node forge-dropship/scripts/get-shopify-token.mjs --client-id <CLIENT_ID>

import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ENV_PATH = path.resolve(HERE, '..', 'config', 'dropship.env');

const PORT = 3456;
const REDIRECT_URI = `http://localhost:${PORT}/callback`;
const SCOPES = [
  'read_products',
  'read_inventory',
  'read_orders',
  'read_fulfillments',
  'read_customers',
  'read_locations',
].join(',');

function arg(name) {
  const i = process.argv.indexOf(`--${name}`);
  return i > -1 ? process.argv[i + 1] : '';
}

function readEnv(file) {
  const cfg = {};
  if (!fs.existsSync(file)) return cfg;
  for (const raw of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#') || !line.includes('=')) continue;
    const i = line.indexOf('=');
    cfg[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  return cfg;
}

// Replace the SHOPIFY_ADMIN_TOKEN line in place, leaving everything else alone.
function writeToken(file, token) {
  const original = fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : '';
  const line = `SHOPIFY_ADMIN_TOKEN=${token}`;
  const re = /^[ \t]*SHOPIFY_ADMIN_TOKEN[ \t]*=.*$/m;
  const updated = re.test(original)
    ? original.replace(re, line)
    : original.replace(/\n*$/, '\n') + line + '\n';
  fs.writeFileSync(file, updated, 'utf8');
}

function promptHidden(question) {
  return new Promise((resolve) => {
    process.stdout.write(question);
    const stdin = process.stdin;
    const wasRaw = stdin.isRaw;
    stdin.setRawMode?.(true);
    stdin.resume();
    stdin.setEncoding('utf8');
    let buf = '';
    const onData = (ch) => {
      if (ch === '\r' || ch === '\n' || ch === '') {
        stdin.setRawMode?.(wasRaw ?? false);
        stdin.pause();
        stdin.removeListener('data', onData);
        process.stdout.write('\n');
        resolve(buf);
      } else if (ch === '') {
        process.exit(130);
      } else if (ch === '' || ch === '\b') {
        buf = buf.slice(0, -1);
      } else {
        buf += ch;
      }
    };
    stdin.on('data', onData);
  });
}

function openBrowser(url) {
  const cmd = process.platform === 'win32' ? 'cmd'
    : process.platform === 'darwin' ? 'open' : 'xdg-open';
  const args = process.platform === 'win32' ? ['/c', 'start', '', url] : [url];
  try { spawn(cmd, args, { detached: true, stdio: 'ignore' }).unref(); } catch { /* user can paste it */ }
}

const die = (msg) => { console.error(msg); process.exit(1); };

const clientId = arg('client-id');
if (!clientId || process.argv.includes('--help')) {
  console.log('usage: node get-shopify-token.mjs --client-id <CLIENT_ID> [--shop <store>.myshopify.com]');
  process.exit(clientId ? 0 : 1);
}

const cfg = readEnv(ENV_PATH);
const shop = arg('shop') || cfg.SHOPIFY_STORE_DOMAIN || '';
if (!shop) die('No shop domain. Pass --shop <store>.myshopify.com');
if (!shop.endsWith('.myshopify.com')) die(`Shop must be the myshopify domain, got "${shop}"`);

let secret = process.env.SHOPIFY_CLIENT_SECRET || '';
if (!secret) secret = (await promptHidden("Paste the app's Client Secret (input hidden): ")).trim();
if (!secret) die('No client secret given.');

const state = crypto.randomBytes(24).toString('base64url');
const authUrl = `https://${shop}/admin/oauth/authorize?` + new URLSearchParams({
  client_id: clientId,
  scope: SCOPES,
  redirect_uri: REDIRECT_URI,
  state,
}).toString();

console.log(`\nStore : ${shop}`);
console.log(`Scopes: ${SCOPES}\n`);
console.log('Opening your browser. Approve the install there.');
console.log(`If it does not open, paste this in manually:\n\n${authUrl}\n`);

const cb = await new Promise((resolve) => {
  const server = http.createServer((req, res) => {
    const u = new URL(req.url, `http://localhost:${PORT}`);
    if (u.pathname !== '/callback') { res.writeHead(404).end(); return; }
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end("<html><body style='font:16px system-ui;padding:40px'><h2>Done.</h2>"
      + '<p>Token captured. Close this tab and go back to the terminal.</p></body></html>');
    resolve({ code: u.searchParams.get('code') || '', state: u.searchParams.get('state') || '' });
    setTimeout(() => server.close(), 100);
  });
  server.listen(PORT, 'localhost', () => openBrowser(authUrl));
});

if (!cb.code) die('No authorization code came back.');
if (cb.state !== state) die('State mismatch — aborting rather than trusting that callback.');

const res = await fetch(`https://${shop}/admin/oauth/access_token`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
  body: JSON.stringify({ client_id: clientId, client_secret: secret, code: cb.code }),
});
if (!res.ok) die(`Token exchange failed: HTTP ${res.status} ${(await res.text()).slice(0, 300)}`);

const payload = await res.json();
const token = payload.access_token || '';
if (!token) die(`No access_token in the response: ${Object.keys(payload).join(', ')}`);

writeToken(ENV_PATH, token);
console.log(`\nWrote SHOPIFY_ADMIN_TOKEN to ${ENV_PATH}`);
console.log(`  length ${token.length}, prefix ${token.slice(0, 6)}…`);
console.log(`  granted scopes: ${payload.scope || '?'}`);
console.log('\nThe token was not printed. Copy the same line to the box at');
console.log('  /opt/forge/forge-dropship/config/dropship.env');
console.log('then: systemctl restart forge-reios');
