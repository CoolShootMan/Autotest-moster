// prefill_shim.js
// Minimal Postman/Apifox `pm` API shim so Apifox test & prerequest scripts run
// natively under Node (no translation, 100% fidelity for the extraction logic).
//
// Usage (invoked by prefill_runner.py):
//   node prefill_shim.js <vars.json> <script.js> [respJson] [statusCode] [respHeadersJson] [reqMetaJson]
//
// Handles Apifox-generated scripts which use:
//   - require('jsonpath-plus') with $.data.token style expressions  -> polyfilled
//   - async IIFE + await pm.variables.replaceIn(...)                 -> awaited
//   - pm.environment.set / collectionVariables.set                  -> variable pool
//   - pm.test / pm.expect chains                                     -> lenient (never fatal)
//   - pm.request.body.raw / pm.request.url                          -> from reqMetaJson (7th arg)
//
// The variable pool is written back AFTER the microtask queue drains, so
// values set inside async IIFEs are captured.

const fs = require('fs');
const Module = require('module');

const VARFILE = process.argv[2];
const SCRIPT = process.argv[3];
// argv[4] is a PAYLOAD file path (avoids Windows [WinError 206] cmdline limit)
let PAYLOAD = { resp: null, status: 200, headers: {}, req: null };
if (process.argv[4]) {
  try { PAYLOAD = JSON.parse(fs.readFileSync(process.argv[4], 'utf8')); } catch (e) {}
}
const RESP_JSON = PAYLOAD.resp != null ? PAYLOAD.resp : null;
const RESP_STATUS = PAYLOAD.status || 200;
const RESP_HEADERS = PAYLOAD.headers || {};
const REQ_META = PAYLOAD.req || {};

// --- JSONPath polyfill (covers $.a.b[0].c) ---
function simpleJSONPath(opts) {
  const path = (opts && opts.path) || '';
  const json = opts && opts.json != null ? opts.json : null;
  if (json == null) return undefined;
  let cur = json;
  let p = String(path).replace(/^\$\.?/, '');
  if (!p) return json;
  const segs = p.split('.').filter(Boolean);
  for (const seg of segs) {
    if (cur == null) return undefined;
    const m = seg.match(/^([^\[]+)((?:\[\d+\])*)$/);
    const key = m ? m[1] : seg;
    if (key) cur = cur[key];
    if (m) {
      const idxs = [...seg.matchAll(/\[(\d+)\]/g)].map((x) => parseInt(x[1], 10));
      for (const i of idxs) cur = cur != null ? cur[i] : undefined;
    }
    if (cur === undefined) return undefined;
  }
  return cur;
}

// --- intercept requires used by Apifox-generated scripts ---
const crypto = require('crypto');
const cryptoJSStub = {
  MD5: (text) => ({ toString: () => crypto.createHash('md5').update(String(text)).digest('hex') }),
  // extend lazily if more algorithms are needed
  SHA256: (text) => ({ toString: () => crypto.createHash('sha256').update(String(text)).digest('hex') }),
};

const origRequire = Module.prototype.require;
Module.prototype.require = function (name) {
  if (name === 'jsonpath-plus') return { JSONPath: simpleJSONPath };
  if (name === 'xml2js') return { parseString: (txt, opt, cb) => cb(new Error('xml2js stub unused')) };
  if (name === 'crypto-js') return cryptoJSStub;
  return origRequire.apply(this, arguments);
};

let VARS = {};
try { VARS = JSON.parse(fs.readFileSync(VARFILE, 'utf8')); } catch (e) { /* fresh pool */ }

const chain = new Proxy(function () {}, { get: () => chain, apply: () => chain });
const realResp = {
  json: () => RESP_JSON || {},
  text: () => (typeof RESP_JSON === 'string' ? RESP_JSON : JSON.stringify(RESP_JSON || {})),
  code: RESP_STATUS,
  status: String(RESP_STATUS),
  headers: { get: (n) => {
    if (!n) return null;
    const low = n.toLowerCase();
    for (const k of Object.keys(RESP_HEADERS)) if (k.toLowerCase() === low) return RESP_HEADERS[k];
    return null;
  } },
};
const pmResponse = new Proxy(realResp, { get: (t, p) => (p in t ? t[p] : chain) });

const store = {
  set: (k, v) => { VARS[k] = v; },
  get: (k) => (k in VARS ? VARS[k] : undefined),
  has: (k) => k in VARS,
  unset: (k) => { delete VARS[k]; },
  _expand: (v) => (typeof v === 'string'
    ? v.replace(/\{\{\s*([^}]+)\s*\}\}/g, (m, k) => (k in VARS ? VARS[k] : m))
    : v),
  replaceIn: (v) => store._expand(v),
  replaceInAsync: async (v) => store._expand(v),
};

// Apifox runtime injects these helpers into generated scripts.
global.____formatValues = (value, compareValue, op) => ({ value, compareValue });
global.____string2Array = (value) => (Array.isArray(value) ? value : (value == null ? [] : [value]));

const pm = {
  response: pmResponse,
  environment: store,
  collectionVariables: store,
  variables: store,
  globals: store,
  test: (name, fn) => {
    if (!fn) return;
    try { fn(() => {}); }  // pass a no-op done() so scripts expecting it won't crash
    catch (e) { console.error('[ASSERT FAIL] ' + name + ': ' + e.message); }
  },
  expect: () => chain,
  expectWithKey: () => chain,
  // No-op DB processor: the runner skips database-operation blocks in no-sql
  // mode, but if one ever reaches here we must not throw on pm.dataSource.
  dataSource: () => (() => {}),
  sendRequest: (...a) => { console.warn('[warn] pm.sendRequest ignored in prefill shim'); },
  iterationData: { get: () => undefined },
  info: { iteration: 0, iterationCount: 1 },
  cookies: { get: () => undefined },
  request: {
    url: REQ_META.url || '',
    body: { raw: REQ_META.body_raw || '' },
  },
};

JSON.setEnableBigInt = () => {};
global.pm = pm;
// Bare Postman/Apifox globals that generated scripts reference directly.
global.responseBody = typeof RESP_JSON === 'string' ? RESP_JSON : JSON.stringify(RESP_JSON || {});
global.responseCode = { code: RESP_STATUS, name: String(RESP_STATUS) };
global.request = pm.request;
global.console = console;
if (typeof XMLHttpRequest === 'undefined') global.XMLHttpRequest = function () {};

process.on('unhandledRejection', (e) => console.error('[unhandled] ' + (e && e.message)));

function writeBack() {
  try { fs.writeFileSync(VARFILE, JSON.stringify(VARS, null, 2)); }
  catch (e) { console.error('[WRITE ERROR] ' + e.message); }
}

try {
  const code = fs.readFileSync(SCRIPT, 'utf8');
  eval(code);
} catch (e) {
  console.error('[SCRIPT ERROR] ' + e.message);
}

// Write back AFTER microtasks (async IIFEs) settle, and also on exit.
setTimeout(writeBack, 150);
process.on('exit', writeBack);
