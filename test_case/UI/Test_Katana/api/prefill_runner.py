#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
prefill_runner.py
=================
Data-driven executor for the Apifox "UI Automation Data Pre-configuration"
collection. Converts an exported collection JSON into a runnable Python script
so fixture data can be reset/prefilled WITHOUT Apifox.

Supported export formats (auto-detected by the presence of the "apifoxCli"
top-level key):
  * Apifox CLI format  (*.apifox-cli.json)  -- PREFERRED, keeps all scripts
  * Postman v2.1        (*.postman_collection.json) -- scripts are dropped on
                         export, so only use this if you have no other choice.

Design
------
* Requests, headers, body and {{var}} references are read straight from the
  collection JSON (no hand-written per-step functions -> easy to re-export).
* Variable extraction / assertions in Apifox test & prerequest scripts are
  executed NATIVELY under Node via `prefill_shim.js` (zero translation loss).
* Scripts that perform DATABASE operations (Apifox "database processor") are
  SKIPPED -- this runner is the faithful "no sql" translation of the Apifox
  collection, so no database access is performed. Alias extraction relies
  purely on API responses.
* Control-flow nodes (Apifox test-flow: group / if / delay) are honoured:
    - `if`    : evaluated by its `exists` condition on the referenced variable;
                children run only when the variable is present.
    - `delay` : sleeps the node's `timeout` (milliseconds).

Usage
-----
    python prefill_runner.py \
        --collection "UI Automation Data Pre-configuration staging & release env - no sql.apifox-cli.json" \
        --out . \
        [--env "Apifox environment export.json"] \
        [--base-url https://staging.katana-api.1m.app] \
        [--admin-url https://staging.admin.katana-api.1m.app] \
        [--delay 3] [--dry-run] [--stop-on-fail]

The --env file (Apifox/Postman environment export) is merged into the variable
pool and supersedes collection variables. Any token it holds is auto-mapped to
its account by decoding the JWT `email` claim, so accounts the collection has no
login step for also get fresh tokens.

The final resolved variable pool is written to <out>/prefill_vars.json and a
run log to <out>/prefill_run.log.
"""

import argparse
import base64
import json
import os
import re
import sys
import time
import uuid
import random
import tempfile
import subprocess
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
NODE = r"C:\Users\tester\.workbuddy\binaries\node\versions\22.22.2\node.exe"
SHIM = os.path.join(HERE, "prefill_shim.js")
DEFAULT_COLLECTION = os.path.join(
    HERE,
    "UI Automation Data Pre-configuration staging & release env - no sql.apifox-cli.json",
)

# ---------------------------------------------------------------------------
# Variable resolution
# ---------------------------------------------------------------------------
_DYN = re.compile(r"\{\{\s*\$(string\.uuid|guid|timestamp|randomInt)\s*\}\}")


def _expand_dynamic(s):
    if not isinstance(s, str):
        return s

    def repl(m):
        t = m.group(1)
        if t in ("string.uuid", "guid"):
            return str(uuid.uuid4())
        if t == "timestamp":
            return str(int(time.time()))
        if t == "randomInt":
            return str(random.randint(0, 999999))
        return m.group(0)

    return _DYN.sub(repl, s)


def resolve(template, vars, _depth=0):
    """Replace {{var}} from the pool, then expand dynamic vars ($string.uuid...)."""
    if isinstance(template, str):
        out = re.sub(
            r"\{\{\s*([^}]+)\s*\}\}",
            lambda m: str(vars.get(m.group(1).strip(), m.group(0))),
            template,
        )
        return _expand_dynamic(out)
    if isinstance(template, dict):
        return {k: resolve(v, vars, _depth + 1) for k, v in template.items()}
    if isinstance(template, list):
        return [resolve(v, vars, _depth + 1) for v in template]
    return template


def init_vars(collection):
    v = {}
    for item in collection.get("variable", []):
        k = item.get("key")
        val = item.get("value")
        if k is None or val is None:
            continue
        v[k] = _expand_dynamic(val) if isinstance(val, str) else val
    return v


def load_cli_vars(collection):
    """Load the variable pool from an Apifox CLI export. Variables live in
    `globals.variable.values` and `environment.variable.values` (each a list of
    {key, value}). Environment overrides globals. `BASE_URL` is back-filled
    from `environment.baseUrls.default` when absent (the collection references
    {{BASE_URL}} but stores it only as a baseUrl, not a named variable)."""
    v = {}
    for scope in (collection.get("globals"), collection.get("environment")):
        if not isinstance(scope, dict):
            continue
        var = scope.get("variable")
        if isinstance(var, dict):
            var = var.get("values", [])
        for item in (var or []):
            if not isinstance(item, dict):
                continue
            k = item.get("key")
            val = item.get("value")
            if k is None:
                continue
            v[k] = _expand_dynamic(val) if isinstance(val, str) else val
    # BASE_URL fallback
    if "BASE_URL" not in v:
        bu = collection.get("environment", {}).get("baseUrls", {}).get("default")
        if bu:
            v["BASE_URL"] = bu
    return v


def load_env(env_path):
    """Load an Apifox/Postman environment export ({"values":[{key,value,enabled}]})
    into the variable pool. Returns (dict, list_of_warnings). Enabled values win
    over collection variables so live tokens from the environment take effect."""
    warnings = []
    if not env_path:
        return {}, warnings
    if not os.path.exists(env_path):
        warnings.append("env file not found: %s" % env_path)
        return {}, warnings
    env = json.load(open(env_path, encoding="utf-8"))
    out = {}
    for item in env.get("values", []):
        k = item.get("key")
        val = item.get("value")
        if k is None or val is None:
            continue
        if item.get("enabled", True) is False:
            continue
        out[k] = _expand_dynamic(val) if isinstance(val, str) else val
    return out, warnings


def _load_dotenv_into(vars):
    """Pull DB/secret vars from backend/.env (gitignored) into the pool.
    Only fills keys that are absent, so explicit --env overrides still win.
    Restricted to release_sql_* (the only ones the collection's SQL processor
    needs) to avoid surprising collisions with the API variable pool."""
    p = os.path.join(HERE, "..", "..", "backend", ".env")
    if not os.path.exists(p):
        return
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k.startswith("release_sql_") and k not in vars:
                vars[k] = v


def _run_release_sql(sql, vars, log):
    """Execute one SQL statement against the release Postgres. Used to replicate
    the single Apifox 'database operation' processor (UPDATE PromoterProduct)
    that, despite being shown as disabled in the Apifox UI, actually executes at
    run time (Apifox bug) and is what registers the product as a promoter
    product -- without it the promoter-public GET / curator post 404."""
    try:
        import psycopg2
    except ImportError:
        log("      [sql] psycopg2 not installed -> SKIP DB (promoter nodes will 404)")
        return
    addr = vars.get("release_sql_address")
    user = vars.get("release_sql_username")
    pw = vars.get("release_sql_password")
    db = vars.get("release_sql_name")
    if not all([addr, user, pw, db]):
        log("      [sql] release_sql_* missing in backend/.env -> SKIP DB")
        return
    try:
        conn = psycopg2.connect(host=addr, user=user, password=pw,
                                dbname=db, connect_timeout=10)
        cur = conn.cursor()
        cur.execute(sql)
        conn.commit()
        log("      [sql] OK -> %s" % sql[:90])
        cur.close()
        conn.close()
    except Exception as e:
        log("      [sql] ERROR -> %s" % str(e)[:140])


def _exec_sql_block(exec_lines, vars, log):
    """Extract the actual SQL statement from an Apifox DB-processor script and
    run it. The script builds the query as a backtick template literal passed to
    ____replaceIn(...) / pm.dataSource. We only run blocks that contain a real
    DML statement; the other nodes merely reference pm.dataSource as a string
    and carry no query, so they are skipped safely (no-op)."""
    text = "\n".join(exec_lines or [])
    m = re.search(r"`([^`]*?\b(?:UPDATE|INSERT|SELECT|DELETE)\b[^`]*?)`",
                  text, re.IGNORECASE | re.DOTALL)
    if not m:
        log("      [sql] processor has no actual query -> skip (no-op)")
        return
    sql = resolve(m.group(1), vars)
    _run_release_sql(sql, vars, log)


def extend_auth_map_from_env(vars):
    """Auto-map any JWT-valued variable to its account by decoding the email
    claim. This closes the gap for accounts the collection has no login step for
    (xuan.ext+22, ruicai.ext): their tokens come from --env instead. Existing
    AUTH_EMAIL_MAP entries are NOT overridden (login steps refresh those)."""
    for k, val in vars.items():
        if not isinstance(val, str) or "." not in val:
            continue
        email = _jwt_email("Bearer " + val if not val.startswith("Bearer ") else val)
        if email and email not in AUTH_EMAIL_MAP:
            AUTH_EMAIL_MAP[email] = k


# ---------------------------------------------------------------------------
# Auth injection (closes the hardcoded-JWT gap from the Apifox export)
# ---------------------------------------------------------------------------
AUTH_EMAIL_MAP = {
    "linda.zhou.ext@1m.app": "admin_token",
    "yuxiao.zhu.ext+999@1m.app": "token",
    "yuxiao.zhu.ext+997@1m.app": "partner997_auth_token",
    "yuxiao.zhu.ext+998@1m.app": "coseller_auth_token",
    "yuxiao.zhu.ext+900@1m.app": "token",
    "yuxiao.zhu.ext+901@1m.app": "partner997_auth_token",
    "yuxiao.zhu.ext+9991@1m.app": "token",
}
# Account -> token variable. Used to route folder-level auth for the flattened
# export, where req.auth is null and the account must be inferred from name/URL.
ACCOUNT_TOKEN_VAR = {
    "999": "token",
    "997": "partner997_auth_token",
    "998": "coseller_auth_token",
    "admin": "admin_token",
}
OUT_OF_SCOPE_EMAILS = set()


def _b64url_decode(s):
    s = s + "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)


def _jwt_email(hdr_val):
    """Extract the `email` claim from a 'Bearer eyJ...' header, or None."""
    if not isinstance(hdr_val, str) or not hdr_val.startswith("Bearer eyJ"):
        return None
    try:
        tok = hdr_val.split(" ", 1)[1]
        payload = tok.split(".")[1]
        return json.loads(_b64url_decode(payload)).get("email")
    except Exception:
        return None


def _req_account_email(req):
    """Return the account email if the request carries a hardcoded-JWT
    Authorization header; else None."""
    for h in req.get("header", []):
        if h.get("key", "").lower() != "authorization":
            continue
        email = _jwt_email(h.get("value"))
        if email:
            return email
    return None


def inject_auth(req, vars, log, name=None):
    """Rewrite any hardcoded-JWT authorization header into the variable form
    `Bearer {{<token-var>}}` so the normal {{var}} resolver substitutes the live
    token at send time. A header already a `{{var}}` reference is left untouched.
    `name` is the node name (the request sub-object has no `name` field), needed
    for the 999-token override on the two special-case requests."""
    for h in req.get("header", []):
        if h.get("key", "").lower() != "authorization":
            continue
        raw = h.get("value")
        if not isinstance(raw, str):
            continue
        if "{{" in raw:
            continue
        email = _jwt_email(raw)
        if not email:
            log("      [auth] authorization is a non-JWT literal, kept as-is [WARN]")
            continue
        tv = AUTH_EMAIL_MAP.get(email, "token")
        # Override: these requests carry a 997 (901) auth header in the export
        # but actually run as partner 999 (main account) — verified: the
        # sub-account token returns 403, the 999 token returns 2xx.
        nm = (name or req.get("name") or "").lower()
        if "expired module" in nm or "post to the module" in nm:
            tv = "token"
        h["value"] = "Bearer {{%s}}" % tv
        if not vars.get(tv):
            log("      [auth] %s -> re-bound to {{%s}} but not populated yet [WARN]" % (email, tv))
        else:
            log("      [auth] %s -> re-bound to {{%s}} (was stale literal)" % (email, tv))


# ---------------------------------------------------------------------------
# Account inference (flattened export loses folder-level auth context)
# ---------------------------------------------------------------------------
def _account_key(req, name=None):
    """Infer which partner account a folder-level-auth request belongs to,
    from its name / URL. The Apifox CLI export is flattened (no per-account
    sub-folders), so the folder auth context is lost and must be reconstructed.
    Returns '999' / '997' / '998' / 'admin' / None. `name` is the node name
    (the request sub-object has no `name` field)."""
    name = name or req.get("name") or ""
    url = (url_raw(req) if isinstance(req, dict) else "") or ""
    blob = (name + " " + url).lower()
    # Authorization is initiated by the product owner (999) even when the target
    # is 997/998.
    if "authorize" in blob and "999" in blob:
        return "999"
    # These are partner-999 (main account) operations that merely reference a
    # 997/998 module by name; they MUST run with the 999 token, not the
    # sub-account token (verified: sub-account token returns 403).
    if "expired module" in blob or "post to the module" in blob:
        return "999"
    if "997" in blob:
        return "997"
    if "coseller" in blob or "998" in blob:
        return "998"
    if "admin" in blob:
        return "admin"
    if "999" in blob or "partner999" in blob or "autotestshop" in blob:
        return "999"
    return None


def _resolve_token_var(req, vars, name=None):
    """Pick the right token variable for a request: prefer an explicit
    hardcoded-JWT email mapping, else infer the account from name/URL and map
    it to its dedicated token variable. Falls back to the global `token`."""
    email = _req_account_email(req)
    if email:
        return AUTH_EMAIL_MAP.get(email, "token")
    key = _account_key(req, name)
    if key:
        return ACCOUNT_TOKEN_VAR.get(key, "token")
    return "token"


def _auth_tok_var(req, vars, name=None):
    """The token variable this request is actually authorized with. Prefer an
    explicit Authorization header (inject_auth rewrites it into Bearer {{var}}
    form, including the 999 override for the two special-case requests), else
    fall back to account inference. Re-auth uses this so it always targets the
    SAME account the request's header uses -- eliminating the mismatch where
    inject_auth sent a 999 token but re-auth logged in 997/998."""
    for h in req.get("header", []):
        if h.get("key", "").lower() == "authorization":
            v = h.get("value", "") or ""
            m = re.match(r"Bearer\s*\{\{\s*(\w+)\s*\}\}", v)
            if m:
                return m.group(1)
    return _resolve_token_var(req, vars, name)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def _cli_url_template(req):
    """Build a URL template string from an Apifox CLI `request.url` OBJECT
    ({host:[...], path:[...], query:[{key,value}]}). Variables stay as {{...}}
    so they are resolved later by `resolve()`. If the url is a plain string
    (Postman / some customHttp nodes) it is returned as-is."""
    u = req.get("url")
    if not isinstance(u, dict):
        return u if isinstance(u, str) else ""
    host = u.get("host") or []
    path = u.get("path") or []
    query = u.get("query") or []
    if isinstance(host, list):
        host = "/".join(str(h) for h in host)
    if isinstance(path, list):
        path = "/".join(str(p) for p in path)
    base = host or req.get("baseUrl") or ""
    if base and not base.lower().startswith("http") and not base.startswith("{{"):
        base = "{{BASE_URL}}"
    qs = ""
    if query:
        parts = []
        for q in query:
            if isinstance(q, dict):
                k = q.get("key")
                if k is None:
                    continue
                parts.append("%s=%s" % (k, "" if q.get("value") is None else q.get("value")))
        if parts:
            qs = "?" + "&".join(parts)
    if not path and not qs:
        return base
    sep = "" if (path.startswith("/") if path else False) else "/"
    return base + sep + path + qs


def url_raw(req):
    u = req.get("url")
    if isinstance(u, dict):
        return _cli_url_template(req)
    return u or ""


def fix_double_scheme(u):
    schemes = [m.start() for m in re.finditer(r"https?://", u)]
    if len(schemes) > 1:
        return u[schemes[-1]:]
    return u


def fix_duplicate_query(u):
    m = re.search(r"^(https?://[^?]+)(\?.*)$", u)
    if not m:
        return u
    base, qs = m.group(1), m.group(2)
    seen = set()
    kept = []
    for seg in qs.split("?"):
        for part in seg.split("&"):
            if not part:
                continue
            key = part.split("=", 1)[0] if "=" in part else part
            if key not in seen:
                seen.add(key)
                kept.append(part)
    return base + "?" + "&".join(kept)


def rewrite_legacy_url(method, name, url):
    """Bridge for the old Postman export that still contains v1 endpoints.
    Apifox CLI exports already use v2, so this is effectively a no-op there."""
    if method == "POST" and "Partner Create event" in name and url.rstrip("/").endswith("/product-event"):
        return url + "/v2"
    if method == "GET" and "Partner Check event details" in name:
        url = re.sub(r"/product-event/([^/]+)/details", r"/product-event/v2/\1/config", url)
    if method == "POST" and "/merchant/product" in url and (
        "create general product" in name.lower()
        or "create product and update alias" in name.lower()
        or "create general product and setting no shipping" in name.lower()
    ):
        url = url.replace("/merchant/product", "/v2/products")
    return url


def _ensure_storefront_ready(session, base_url, vanity, headers, log, dry_run):
    """Store-front updates are asynchronous; poll the public shop URL until
    it resolves. This prevents downstream `/promoter/product/public/...`
    404s caused by the storefront not having propagated yet."""
    if dry_run or not vanity:
        return True
    shop_url = base_url.rstrip("/") + "/store-front/shop/" + vanity
    for i in range(6):
        try:
            r = session.get(shop_url, headers=headers, timeout=30)
            if r.status_code == 200:
                return True
        except Exception as e:
            log("      [storefront check %d/6] err -> %s" % (i + 1, str(e)[:60]))
        time.sleep(2)
    return False


def strip_json_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    lines = []
    for line in text.splitlines():
        cleaned = []
        in_str = False
        esc = False
        i = 0
        while i < len(line):
            ch = line[i]
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = not in_str
            elif not in_str and ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
                break
            cleaned.append(ch)
            i += 1
        lines.append("".join(cleaned))
    return "\n".join(lines)


def build_body(req, vars):
    b = req.get("body")
    if not b:
        return None
    mode = b.get("mode")
    if mode == "raw":
        raw = resolve(b.get("raw", ""), vars)
        cleaned = strip_json_comments(raw)
        try:
            return json.loads(cleaned)
        except Exception:
            return raw
    if mode == "urlencoded":
        return {h["key"]: resolve(h["value"], vars) for h in b.get("urlencoded", []) if h.get("value") is not None}
    if mode == "formdata":
        return {h["key"]: resolve(h["value"], vars) for h in b.get("formdata", []) if h.get("value") is not None}
    if mode == "graphql":
        return resolve(b.get("graphql", {}).get("query", ""), vars)
    raw = b.get("raw")
    return resolve(raw, vars) if raw else None


VARS_TMP = os.path.join(tempfile.gettempdir(), "_prefill_vars_tmp.json")


def _resolved_raw_body(req, vars):
    b = req.get("body")
    if not b:
        return None
    raw = b.get("raw")
    return strip_json_comments(resolve(raw, vars)) if raw else None


# ---------------------------------------------------------------------------
# Script execution (Node shim)
# ---------------------------------------------------------------------------
def _is_sql_block(exec_lines):
    """Detect Apifox 'database operation' processors -- skipped in this
    no-sql runner. We only skip blocks that actually call `pm.dataSource(...)`
    or are tagged as DB processors; ordinary JS (incl. variable extraction)
    runs natively via the Node shim."""
    text = "\n".join(exec_lines or [])
    return ("pm.dataSource" in text
            or "__label_placeholder__processor__" in text
            or "数据库操作" in text)


def run_script(exec_lines, vars, resp, node, log, req_meta=None):
    code = "\n".join(exec_lines or [])
    if not code.strip():
        return
    tf = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    tf.write(code)
    tf.close()
    vfile = VARS_TMP
    with open(vfile, "w", encoding="utf-8") as f:
        json.dump(vars, f, ensure_ascii=False)
    resp_json = None
    if resp is not None:
        try:
            resp_json = resp.json()
        except Exception:
            resp_json = None
    headers = dict(resp.headers) if resp is not None else {}
    status = resp.status_code if resp is not None else 200
    payload = {"resp": resp_json, "status": status, "headers": headers, "req": req_meta}
    pf = tempfile.NamedTemporaryFile("w", suffix=".payload.json", delete=False, encoding="utf-8")
    json.dump(payload, pf, ensure_ascii=False)
    pf.close()
    cmd = [node, SHIM, vfile, tf.name, pf.name]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=HERE)
        if r.stderr.strip():
            for line in r.stderr.strip().splitlines()[:3]:
                log("      [script] " + line[:160])
    except subprocess.TimeoutExpired:
        log("      [script] TIMEOUT executing JS")
    except Exception as e:
        log("      [script] ERROR " + str(e)[:160])
    try:
        with open(vfile, encoding="utf-8") as f:
            vars.update(json.load(f))
    except Exception:
        pass
    for p in (tf.name, pf.name):
        try:
            os.remove(p)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Token auto-refresh (release JWTs expire in ~120s; the prefill flow runs
# 200s+, so tokens must be refreshed mid-run or every late request 403s with
# "please log in again to continue").
# ---------------------------------------------------------------------------
LOGIN_NODES = {}
# Circuit breaker: if an account's login fails N times in a row, stop auto
# re-playing it. Otherwise a persistent 403 (bad creds / locked account)
# makes the runner hammer the login endpoint and trip the server's
# brute-force lockout ("Your account has been blocked" / "Too many logins").
CIRCUIT_THRESHOLD = 2
ACCOUNT_LOGIN_FAILS = {}

def _jwt_exp(token):
    try:
        tok = token.split(" ", 1)[1] if isinstance(token, str) and token.startswith("Bearer ") else token
        if not isinstance(tok, str) or "." not in tok:
            return None
        payload = tok.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("exp")
    except Exception:
        return None

def _token_expiring(token, secs):
    exp = _jwt_exp(token)
    if exp is None:
        return False
    return (exp - time.time()) < secs

def _classify_login(name):
    """Classify a node as a login endpoint for its account so the runner can
    replay it to refresh an expiring JWT. CRITICAL: only nodes whose name
    contains 'login' qualify -- the collection also has 'set partner999
    password' style nodes that appear EARLIER in the flat list and share the
    account digits; classifying those as login nodes made the refresh loop
    replay a password-set request (which returns no token) -> infinite
    re-login. Verified real login nodes: 'admin login', 'Partner 999 login',
    'Partner 997 login', 'Coseller 998 login'."""
    n = (name or "").lower()
    if "login" not in n:
        return None
    if "admin" in n:
        return "admin"
    if "997" in n:
        return "997"
    if "998" in n:
        return "998"
    if "999" in n or "partner" in n:
        return "999"
    return None

def _collect_login_nodes(nodes, out):
    for n in nodes:
        if n.get("type") in ("http", "customHttp") or "request" in n:
            acc = _classify_login(n.get("name", ""))
            if acc and acc not in out:
                out[acc] = n
        elif isinstance(n.get("item"), list):
            _collect_login_nodes(n["item"], out)

_TOKEN_VARS = (("token", "999"), ("partner997_auth_token", "997"),
               ("coseller_auth_token", "998"), ("admin_token", "admin"))

def _refresh_expiring_tokens(vars, ctx):
    """Re-login any account whose token expires within 40s so subsequent
    requests don't 403 with 'please log in again to continue'."""
    if ctx.get("in_login_refresh"):
        return
    log = ctx.get("log", lambda m: None)
    for varname, account in _TOKEN_VARS:
        tv = vars.get(varname)
        if not tv or not _token_expiring(tv, 40):
            continue
        node = LOGIN_NODES.get(account)
        if not node:
            continue
        if ACCOUNT_LOGIN_FAILS.get(account, 0) >= CIRCUIT_THRESHOLD:
            log("      [auth] %s circuit-OPEN (%d consecutive login failures) -> skip re-login (avoid lockout)"
                % (account, ACCOUNT_LOGIN_FAILS[account]))
            continue
        ctx["in_login_refresh"] = True
        try:
            log("      [auth] %s token expiring -> auto re-login" % account)
            handle_req(node, ctx, None)
        finally:
            ctx["in_login_refresh"] = False


def _tv_to_acc(tv):
    return {"token": "999", "partner997_auth_token": "997",
            "coseller_auth_token": "998", "admin_token": "admin"}.get(tv)


def _is_token_expired(resp):
    """True when the server rejected the request because our JWT died."""
    if resp is None:
        return False
    try:
        body = resp.text or ""
    except Exception:
        return False
    low = body.lower()
    return "please log in again" in low or "log in again" in low


def _reauth(ctx, acc):
    """Replay the account's login node to obtain a fresh JWT. Returns True if a
    non-empty token was written back into vars (so the caller can retry)."""
    if ACCOUNT_LOGIN_FAILS.get(acc, 0) >= CIRCUIT_THRESHOLD:
        return False
    node = LOGIN_NODES.get(acc)
    if not node:
        return False
    prev = ctx.get("in_login_refresh")
    ctx["in_login_refresh"] = True
    try:
        handle_req(node, ctx, None)
    finally:
        ctx["in_login_refresh"] = prev
    tv = {"999": "token", "997": "partner997_auth_token",
          "998": "coseller_auth_token", "admin": "admin_token"}[acc]
    if ctx["vars"].get(tv):
        ACCOUNT_LOGIN_FAILS[acc] = 0  # a successful re-login clears the counter
        return True
    return False


def handle_req(it, ctx, ignore_status=None):
    req = it.get("request") or it
    name = it.get("name") or (req.get("name") if isinstance(req, dict) else None) or "?"
    vars = ctx["vars"]
    # Tokens are refreshed on-demand: when a request 403s with an expired-token
    # message we re-login the owning account and retry (see the send loop).
    # This is simpler and more robust than proactively replaying logins mid-flow.
    log = ctx["log"]
    session = ctx["session"]
    ignore_status = ignore_status or set()

    if ctx["dry_run"]:
        method = req.get("method") if isinstance(req, dict) else None
        url = resolve(url_raw(req) if isinstance(req, dict) else "", vars)
        log("[DRY] %-6s %s" % (method, name))
        return

    scope_email = _req_account_email(req) if isinstance(req, dict) else None
    if scope_email in OUT_OF_SCOPE_EMAILS:
        log("[SKIP] %s %s -> out-of-scope account %s (hard boundary)" % (
            req.get("method", "?"), name, scope_email))
        return

    # Apifox CLI uses singular `event`; Postman uses `events`. Apifox's
    # "extract variable" post-processors live in metaInfo.events and MUST be
    # run too, or response-extracted vars (productId0, ...) stay empty.
    events = list(it.get("event") or it.get("events") or [])
    events += list((it.get("metaInfo") or {}).get("events") or [])

    # prerequest (may set vars used in body)
    for e in events:
        if e.get("listen") == "prerequest":
            exec_lines = (e.get("script") or {}).get("exec", [])
            if _is_sql_block(exec_lines):
                _exec_sql_block(exec_lines, vars, log)
                continue
            req_meta = {"body_raw": _resolved_raw_body(req, vars),
                        "url": fix_duplicate_query(fix_double_scheme(resolve(url_raw(req), vars)))}
            run_script(exec_lines, vars, None, ctx["node"], log, req_meta)

    method = req.get("method")
    inject_auth(req, vars, log, name)
    url_template = url_raw(req)
    if "Partner Check event details" in name:
        url_template = url_template.replace("/{id}/", "/{{created_event_id}}/")
    url = rewrite_legacy_url(method, name, fix_duplicate_query(fix_double_scheme(resolve(url_template, vars))))
    # Guard: the `delete the users and check the user delete success` nodes use
    # {{user_id}} / {{user_coseller_id}} / {{user_partner997_id}}. After a reset
    # (or when an account simply doesn't exist) those vars are empty, and the
    # request would resolve to a malformed `/users/` URL. Skip it instead of
    # sending a broken request. The walk re-creates the account afterwards and
    # the post-create search re-populates the id.
    for _iv in ("user_id", "user_coseller_id", "user_partner997_id"):
        if ("{{%s}}" % _iv) in url_template and not str(vars.get(_iv, "")).strip():
            log("[SKIP] %s -> {{%s}} unresolved (account not present) -> skip" % (name, _iv))
            return
    # Apifox "global header parameters" are sent on EVERY business request.
    global_headers = {
        "Pear-AutoTesting": "{{Pear-AutoTesting}}",
        "Pear-Client-Id": "{{pear_client_id}}",
        "Pear-Client-Secret": "{{pear_client_secret}}",
    }
    request_headers = {
        h["key"]: resolve(h["value"], vars)
        for h in req.get("header", [])
        if h.get("value") is not None and h.get("key", "").lower() not in ("if-none-match", "if-modified-since", "cache-control")
    }
    merged = {k: resolve(v, vars) for k, v in global_headers.items()}
    merged.update(request_headers)
    headers = merged
    # Default token only when the request is actually authenticated.
    auth = req.get("auth") or {}
    auth_noauth = (auth.get("type") == "noauth")
    if not any(k.lower() == "authorization" for k in headers):
        if auth_noauth:
            log("      [auth] noauth request -> no default token added")
        else:
            tok_var = _resolve_token_var(req, vars, name)
            tok = vars.get(tok_var)
            if tok:
                headers["authorization"] = "Bearer " + str(tok)
                log("      [auth] no auth header in export -> defaulted to {{%s}}" % tok_var)
            else:
                log("      [auth] no auth header and {{%s}} empty [WARN]" % tok_var)
    body = build_body(req, vars)
    is_json_body = isinstance(body, (dict, list))
    req_meta = {"body_raw": _resolved_raw_body(req, vars), "url": url}

    # Retry SSL handshakes and transient async-propagation 404s. Public
    # promoter product detail and curator posts both depend on products that
    # the server indexes asynchronously; Apifox hides this latency behind
    # interactive pacing between requests.
    is_promoter_detail = (method or "").upper() == "GET" and "/promoter/product/public/" in url
    is_post_curator = (method or "").upper() == "POST" and url.rstrip("/").endswith("/posts/curator")
    is_storefront_update = (method or "").upper() == "PUT" and url.rstrip("/").endswith("/store-front")
    should_retry_404 = is_promoter_detail or is_post_curator
    base_url = req.get("baseUrl") or (re.match(r"(https?://[^/]+)", url).group(1) if re.match(r"https?://", url) else "")
    # Curator posts reference merchant products that need a few minutes to
    # become "postable"; give them a much longer 404-retry window than the
    # product-detail lookups (which resolve faster).
    max_attempts = 4 if should_retry_404 else 2
    attempt = 0
    resp = None
    last_status = None
    reauthed = False
    while attempt < max_attempts:
        attempt += 1
        try:
            resp = session.request(
                method, url, headers=headers,
                json=body if is_json_body else None,
                data=body if not is_json_body else None,
                timeout=60,
            )
            last_status = resp.status_code
            ignored = last_status in ignore_status
            ok = last_status < 400 or ignored
            # Async propagation: the referenced product/alias may not be indexed
            # yet. Back off and retry.
            if should_retry_404 and last_status == 404 and attempt < max_attempts:
                wait = 8
                log("      [retry %d/%d] 404 -> waiting %.0fs for async propagation" % (attempt, max_attempts, wait))
                time.sleep(wait)
                continue
            # On-demand re-auth: a 401/403 with an expired-token message means our
            # JWT died. Re-login the owning account once and retry the request.
            if (not reauthed and "login" not in (name or "").lower()
                    and last_status in (401, 403) and _is_token_expired(resp)):
                acc = _tv_to_acc(_auth_tok_var(req, vars, name))
                if acc and _reauth(ctx, acc):
                    reauthed = True
                    tok_var = _auth_tok_var(req, vars, name)
                    tok = vars.get(tok_var)
                    if tok:
                        headers["authorization"] = "Bearer " + str(tok)
                    log("      [auth] token expired -> re-logged in %s, retrying %s" % (acc, name))
                    continue
                else:
                    log("      [auth] token expired on %s but re-login %s failed/skipped -> request will fail"
                        % (name, acc))
            tag = "OK " if ok else "FAIL"
            note = " [ignored %d]" % last_status if ignored else ""
            log("[%s] %-6s %s -> %d%s" % (tag, method, name, last_status, note))
            if not ok and resp is not None:
                try:
                    snippet = resp.text[:300].replace("\n", " ")
                except Exception:
                    snippet = "<unreadable>"
                log("      [resp] %s" % snippet)
            # User deletion on this platform is asynchronous and may race with
            # the subsequent re-creation of the same email. Pause briefly to
            # let the deletion propagate before we recreate the account.
            if (method or "").upper() == "DELETE" and last_status == 200 and "/users/" in url:
                log("      [wait] user deletion -> sleep 5s for async propagation")
                if not ctx["dry_run"]:
                    time.sleep(5)
            # Store-front updates are also asynchronous; wait until the public
            # shop URL resolves before continuing.
            if is_storefront_update and ok and not ctx["dry_run"]:
                vanity = (body or {}).get("userInfo", {}).get("vanityUrl") if isinstance(body, dict) else None
                if vanity:
                    log("      [storefront] verifying /store-front/shop/%s is reachable" % vanity)
                    if not _ensure_storefront_ready(session, base_url, vanity, headers, log, ctx["dry_run"]):
                        log("      [WARN] storefront not reachable after update")
            if not ok and ctx.get("stop_on_fail"):
                raise SystemExit("stop-on-fail: %s returned %d" % (name, last_status))
            break
        except SystemExit:
            raise
        except requests.exceptions.SSLError as ex:
            if attempt < max_attempts:
                log("      [retry %d/%d] SSL error -> %s" % (attempt, max_attempts, str(ex)[:60]))
                time.sleep(1)
                continue
            log("[ERR] %-6s %s -> SSLError after %d retries: %s" % (method, name, attempt, ex))
            resp = None
        except Exception as ex:
            log("[ERR] %-6s %s -> %s" % (method, name, ex))
            resp = None
            break

    # test scripts (extract vars + assertions, plus PostgreSQL processors)
    for e in events:
        if e.get("listen") == "test":
            exec_lines = (e.get("script") or {}).get("exec", [])
            if _is_sql_block(exec_lines):
                _exec_sql_block(exec_lines, vars, log)
                continue
            run_script(exec_lines, vars, resp, ctx["node"], log, req_meta)

    # Pacing for the create-product step: it triggers async indexing, and the
    # following promoter/alias lookups can 404 if they run before the product
    # is indexed. Apifox paces these interactively; we keep a fixed wait so
    # the main flow stays faithful 1:1 to the collection.
    if "create product and update alias" in name and not ctx.get("_promo_wait_done"):
        ctx["_promo_wait_done"] = True
        if not ctx["dry_run"]:
            log("      [wait] create-product async indexing -> sleep 15s")
            time.sleep(15)


def handle_if(folder, ctx):
    """Postman-style `if` folder (delete-then-create reset semantics)."""
    vars = ctx["vars"]
    log = ctx["log"]
    for child in folder.get("item", []):
        if "request" not in child:
            continue
        url = url_raw(child.get("request", child))
        m = re.search(r"\{\{\s*([\w]+_id)\s*\}\}", url)
        cond_var = m.group(1) if m else None
        if cond_var:
            if vars.get(cond_var):
                log("[IF] %s present -> EXECUTE delete %s" % (cond_var, child["name"]))
                handle_req(child, ctx, ignore_status={404, 410})
            else:
                log("[IF] %s absent -> SKIP delete %s" % (cond_var, child["name"]))
        else:
            log("[IF] condition unknown (lost in export) -> EXECUTE %s [WARN]" % child["name"])
            handle_req(child, ctx, ignore_status={404, 410})


def handle_if_cli(node, ctx):
    """Apifox test-flow `if` node. Condition lives in metaInfo.parameters
    ({keyVariable, operator}). We honour `exists`/`notExist`; children run
    only when the condition passes."""
    vars = ctx["vars"]
    log = ctx["log"]
    params = (node.get("metaInfo") or {}).get("parameters", {})
    keyvar = (params.get("keyVariable") or "").strip().strip("{} ").strip()
    operator = params.get("operator", "exists")
    present = bool(vars.get(keyvar)) if keyvar else True
    if operator == "notExist":
        passes = not present
    else:  # exists (default)
        passes = present
    if keyvar and passes:
        log("[IF] %s %s -> EXECUTE %d children" % (keyvar, operator, len(node.get("item", []))))
        walk(node.get("item", []), ctx, ignore_status={404, 410})
    else:
        log("[IF] %s %s -> SKIP children" % (keyvar or "?", operator))


def handle_delay(folder, ctx):
    ctx["log"]("[DELAY] sleep %ds [WARN: Apifox delay seconds lost, using default]" % ctx["delay"])
    if not ctx["dry_run"]:
        time.sleep(ctx["delay"])


def handle_delay_cli(node, ctx):
    to = (node.get("metaInfo") or {}).get("timeout", 3000)
    # Apifox stores delay in milliseconds.
    secs = to / 1000.0 if to and to > 100 else (to or 3)
    ctx["log"]("[DELAY] sleep %.1fs" % secs)
    if not ctx["dry_run"]:
        time.sleep(secs)


def walk(items, ctx, ignore_status=None):
    for it in items:
        t = it.get("type")
        if t in ("http", "customHttp"):
            handle_req(it, ctx, ignore_status)
            if not ctx["dry_run"]:
                time.sleep(ctx.get("delay", 2))
        elif t == "group":
            walk(it.get("item", []), ctx, ignore_status)
        elif t == "if":
            handle_if_cli(it, ctx)
        elif t == "delay":
            handle_delay_cli(it, ctx)
        elif "item" in it:
            # Postman-style folder or unknown container -> recurse
            name = it.get("name", "")
            if name == "if":
                handle_if(it, ctx)
            elif name == "delay":
                handle_delay(it, ctx)
            else:
                walk(it["item"], ctx, ignore_status)
        elif "request" in it:
            handle_req(it, ctx, ignore_status)


def main():
    ap = argparse.ArgumentParser(description="Run Apifox prefill collection without Apifox")
    ap.add_argument("--collection", default=DEFAULT_COLLECTION)
    ap.add_argument("--out", default=HERE)
    ap.add_argument("--env", default=None, help="Apifox/Postman environment export (supplies live tokens)")
    ap.add_argument("--base-url", default=None, help="override {{BASE_URL}}")
    ap.add_argument("--admin-url", default=None, help="override {{adminurl}}")
    ap.add_argument("--delay", type=int, default=2, help="seconds between nodes (mirrors Apifox step delays)")
    ap.add_argument("--dry-run", action="store_true", help="print plan, send no HTTP")
    ap.add_argument("--stop-on-fail", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.collection):
        print("collection not found:", args.collection)
        sys.exit(1)

    collection = json.load(open(args.collection, encoding="utf-8"))
    is_cli = "apifoxCli" in collection
    if is_cli:
        vars = load_cli_vars(collection)
        fmt = "Apifox CLI (%s)" % collection.get("apifoxCli")
    else:
        vars = init_vars(collection)
        fmt = "Postman v2.1"

    # Pull release DB credentials from backend/.env (gitignored). Only fills
    # release_sql_* keys that are absent, so --env overrides still win.
    _load_dotenv_into(vars)

    if args.env:
        env_vars, env_warn = load_env(args.env)
        for w in env_warn:
            print("[env] " + w)
        vars.update(env_vars)
        extend_auth_map_from_env(vars)
        print("=== env loaded: %d vars, %d auth mappings now known ==="
              % (len(env_vars), len(AUTH_EMAIL_MAP)))
    if args.base_url:
        vars["BASE_URL"] = args.base_url
    if args.admin_url:
        vars["adminurl"] = args.admin_url

    os.makedirs(args.out, exist_ok=True)
    log_lines = []

    def log(msg):
        print(msg)
        log_lines.append(msg)

    session = requests.Session()
    ctx = {
        "vars": vars,
        "session": session,
        "node": NODE,
        "log": log,
        "dry_run": args.dry_run,
        "stop_on_fail": args.stop_on_fail,
        "delay": args.delay,
    }

    log("=== prefill_runner: %s ===" % collection.get("info", {}).get("name", "?"))
    log("=== format: %s | mode: %s ===" % (fmt, "DRY-RUN" if args.dry_run else "LIVE"))
    t0 = time.time()
    try:
        _collect_login_nodes(collection.get("item", []), LOGIN_NODES)
        walk(collection.get("item", []), ctx)
    finally:
        with open(os.path.join(args.out, "prefill_run.log"), "w", encoding="utf-8") as f:
            f.write("\n".join(log_lines))
        with open(os.path.join(args.out, "prefill_vars.json"), "w", encoding="utf-8") as f:
            json.dump(vars, f, ensure_ascii=False, indent=2)
    log("=== done in %.1fs ===" % (time.time() - t0))
    log("=== vars written: %s ===" % os.path.join(args.out, "prefill_vars.json"))


if __name__ == "__main__":
    main()
