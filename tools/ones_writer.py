#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ONES Test Case Writer — create test cases via ONES REST API.

Usage:
    # Create a single test case from JSON
    python tools/ones_writer.py create case.json

    # Batch create from a JSON array file
    python tools/ones_writer.py batch cases.json

    # List modules in the Katana library
    python tools/ones_writer.py modules

    # List test plans
    python tools/ones_writer.py plans

    # Add cases to a test plan
    python tools/ones_writer.py add-to-plan <plan_uuid> <case_uuid1> [case_uuid2 ...]

    # Refresh token (if expired)
    python tools/ones_writer.py refresh-token

Case JSON format:
    {
        "name": "Verify form redirect after submission",
        "module_uuid": "<from ONES module list or env ONES_DEFAULT_MODULE_UUID>",
        "condition": "Form is created and published",
        "desc": "<p>KAT-11397: Test redirect URL</p>",
        "steps": [
            {"desc": "Step 1 description", "result": "Expected result"},
            {"desc": "Step 2 description", "result": "Expected result"}
        ],
        "priority": "normal",
        "type": "functional"
    }

    priority: "highest" | "high" | "normal" | "low" | "lowest" (default: "normal")
    type: "functional" | "performance" | "api" | "install" | "config" | "safety" | "other"
    module_uuid: optional, defaults to env ONES_DEFAULT_MODULE_UUID or root module
"""
import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
ENV_PATH = PROJECT_DIR / "backend" / ".env"

ONES_LOGIN_URL = "https://ones.cn/identity/login"

# Fallback default module UUID. Prefer setting ONES_DEFAULT_MODULE_UUID in backend/.env
# so that each ticket can target the correct module instead of hardcoding a historical one.
DEFAULT_MODULE_UUID = "2ojXUdsv"


def load_env():
    """Load credentials from backend/.env."""
    env = {}
    if ENV_PATH.exists():
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env


def save_env(updates: dict):
    """Update specific keys in backend/.env without losing others."""
    lines = []
    if ENV_PATH.exists():
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()

    updated_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            k = stripped.split("=", 1)[0].strip()
            if k in updates:
                new_lines.append(f"{k}={updates[k]}\n")
                updated_keys.add(k)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    # Add any keys that weren't already in the file
    for k, v in updates.items():
        if k not in updated_keys:
            new_lines.append(f"{k}={v}\n")

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


# Priority mapping (P0/P1 only as required)
PRIORITY_MAP = {
    "highest": "3g7bLpa1",   # P0
    "high": "VRXHXgbp",      # P1
}

TYPE_MAP = {
    "functional": "7qLS7W5f",     # 功能测试
    "performance": "Av5GQKDJ",    # 性能测试
    "api": "7qLS7W5f",            # fallback to functional until API type UUID is found
    "install": "7qLS7W5f",
    "config": "7qLS7W5f",
    "safety": "7qLS7W5f",
    "other": "7qLS7W5f",
}


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------

def refresh_token_via_playwright() -> str:
    """Login to ONES via Playwright and extract a fresh JWT token."""
    print("  Token expired or invalid. Refreshing via Playwright login...")
    from playwright.sync_api import sync_playwright

    env = load_env()
    ones_email = env.get("ONES_EMAIL", "")
    ones_password = env.get("ONES_PASSWORD", "")
    if not ones_email or not ones_password:
        print("  ERROR: ONES_EMAIL and ONES_PASSWORD must be set in backend/.env", file=sys.stderr)
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        page.set_default_timeout(30000)

        page.goto(ONES_LOGIN_URL)
        page.get_by_role("textbox", name="* 邮箱").fill(ones_email)
        page.get_by_role("textbox", name="* 密码").fill(ones_password)
        page.get_by_role("button", name="登录").click()
        page.wait_for_timeout(3000)

        # Navigate to test management to ensure token is set
        try:
            page.get_by_role("link", name="测试管理").click()
            page.wait_for_timeout(2000)
        except Exception:
            pass

        # Extract token from cookie "ones-lt"
        token = None
        for cookie in context.cookies():
            if cookie["name"] == "ones-lt" and len(cookie["value"]) > 20:
                token = cookie["value"]
                break

        context.close()
        browser.close()

    if not token:
        print("  ERROR: Could not extract token after login!", file=sys.stderr)
        sys.exit(1)

    # Save to .env
    save_env({"ONES_AUTH_TOKEN": token})
    print(f"  Token refreshed and saved to .env")
    return token


def ensure_token(env: dict) -> str:
    """Check if token is valid; refresh if expired."""
    token = env.get("ONES_AUTH_TOKEN", "")
    if not token:
        token = refresh_token_via_playwright()
        env["ONES_AUTH_TOKEN"] = token
        return token

    # Verify token
    status, _ = api_call("GET", "/project/api/project/users/me", env=env)
    if status == 200:
        return token

    # Token invalid, refresh
    token = refresh_token_via_playwright()
    env["ONES_AUTH_TOKEN"] = token
    return token


# ---------------------------------------------------------------------------
# API layer
# ---------------------------------------------------------------------------

def api_call(method: str, path: str, body=None, env: dict = None):
    """Make an authenticated API call to ONES."""
    if env is None:
        env = load_env()

    base_url = env.get("ONES_URL", "https://sz.ones.cn")
    token = env.get("ONES_AUTH_TOKEN", "")
    url = f"{base_url}{path}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-request-csrf-token": "1",
    }

    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        return e.code, body_text[:500]
    except Exception as e:
        return 0, str(e)


def graphql(query: str, variables: dict = None, env: dict = None):
    """Execute a GraphQL query."""
    if env is None:
        env = load_env()
    team_uuid = env.get("ONES_TEAM_UUID", "T7u1zXum")
    path = f"/project/api/project/team/{team_uuid}/items/graphql"
    body = {"query": query, "variables": variables or {}}
    return api_call("POST", path, body, env=env)


# ---------------------------------------------------------------------------
# Domain operations
# ---------------------------------------------------------------------------

def get_libraries(env: dict):
    """Get test case libraries."""
    team = env.get("ONES_TEAM_UUID", "T7u1zXum")
    status, resp = api_call("GET", f"/project/api/project/team/{team}/testcase/libraries", env=env)
    if status == 200 and isinstance(resp, dict):
        return resp.get("libraries", [])
    return []


def get_modules(env: dict, library_uuid: str = None):
    """Get top-level modules in a library via GraphQL."""
    if library_uuid is None:
        library_uuid = env.get("ONES_LIBRARY_UUID", "XcAFFViB")

    query = """
    query QUERY_MODULES_IN_LIBRARY($moduleFilter: Filter) {
        testcaseModules(
            filter: $moduleFilter,
            groupBy: { testcaseLibrary: {} },
            orderBy: { isDefault: ASC, position: ASC }
        ) {
            key
            uuid
            parent { key, uuid }
            position
            name
            path
            testcaseCaseCount
            isDefault
        }
    }
    """
    variables = {
        "moduleFilter": {
            "testcaseLibrary_in": [library_uuid],
        }
    }
    status, resp = graphql(query, variables, env=env)
    if status == 200 and isinstance(resp, dict) and "data" in resp:
        return resp["data"].get("testcaseModules", [])
    print(f"  Warning: GraphQL modules query returned {status}: {str(resp)[:200]}", file=sys.stderr)
    return []


def resolve_module_uuid(case_data: dict, env: dict, override_module: str = None) -> str:
    """Resolve module UUID with clear precedence:
    1. Command-line override (--module <uuid>)
    2. module_uuid field inside the case JSON
    3. env ONES_DEFAULT_MODULE_UUID
    4. historical fallback DEFAULT_MODULE_UUID
    """
    if override_module:
        return override_module
    if case_data and case_data.get("module_uuid"):
        return case_data["module_uuid"]
    return env.get("ONES_DEFAULT_MODULE_UUID") or DEFAULT_MODULE_UUID


def get_plans(env: dict):
    """Get test plans."""
    team = env.get("ONES_TEAM_UUID", "T7u1zXum")
    status, resp = api_call("GET", f"/project/api/project/team/{team}/testcase/plans", env=env)
    if status == 200 and isinstance(resp, dict):
        return resp.get("plans", [])
    return []


def _short_uuid():
    return uuid.uuid4().hex[:8]


def update_case_steps(case_uuid: str, case_data: dict, env: dict, override_module: str = None):
    """Write steps to a test case using the real ONES REST endpoint.

    The generic /items/add endpoint silently drops steps.  The only reliable
    way to persist them is POST /testcase/library/{library_uuid}/cases/update.
    Returns (success: bool, message: str).
    """
    team = env.get("ONES_TEAM_UUID", "T7u1zXum")
    library_uuid = env.get("ONES_LIBRARY_UUID", "XcAFFViB")
    user_id = env.get("ONES_USER_ID", "HKJxJn4E")

    type_key = case_data.get("type", "functional")
    type_uuid = TYPE_MAP.get(type_key, TYPE_MAP["functional"])
    module_uuid = resolve_module_uuid(case_data, env, override_module)
    priority_uuid = PRIORITY_MAP.get(case_data.get("priority", "high"), PRIORITY_MAP["high"])

    raw_steps = case_data.get("steps", [])
    steps = []
    for i, s in enumerate(raw_steps):
        if isinstance(s, dict):
            step_uuid = _short_uuid()
            steps.append({
                "desc": s.get("desc", ""),
                "result": s.get("result", ""),
                "index": i,
                "key": f"testcase_case_step-{step_uuid}",
                "testcaseCase": {"uuid": case_uuid},
                "uuid": step_uuid,
            })
        elif isinstance(s, str):
            step_uuid = _short_uuid()
            steps.append({
                "desc": s,
                "result": "",
                "index": i,
                "key": f"testcase_case_step-{step_uuid}",
                "testcaseCase": {"uuid": case_uuid},
                "uuid": step_uuid,
            })

    body = {
        "cases": [
            {
                "uuid": case_uuid,
                "name": case_data["name"],
                "condition": case_data.get("condition", ""),
                "desc": case_data.get("desc") or case_data.get("description", ""),
                "library_uuid": library_uuid,
                "module_uuid": module_uuid,
                "assign": case_data.get("assign", user_id),
                "type": type_uuid,
                "priority": priority_uuid,
                "steps": steps,
            }
        ]
    }

    path = f"/project/api/project/team/{team}/testcase/library/{library_uuid}/cases/update"
    status, resp = api_call("POST", path, body, env=env)
    if status == 200 and isinstance(resp, dict) and resp.get("errcode") == "OK":
        return True, f"{len(steps)} steps written"
    return False, f"{status}: {str(resp)[:300]}"


def create_case(case_data: dict, env: dict, override_module: str = None):
    """Create a single test case.

    case_data keys:
        name (required), module_uuid, condition, desc (or description —
        both accepted), steps, priority ("normal"|"high"|...),
        type ("functional"|...), assign (optional, defaults to current user)
    """
    team = env.get("ONES_TEAM_UUID", "T7u1zXum")
    library_uuid = env.get("ONES_LIBRARY_UUID", "XcAFFViB")
    user_id = env.get("ONES_USER_ID", "HKJxJn4E")

    priority_key = case_data.get("priority", "high")
    priority_uuid = PRIORITY_MAP.get(priority_key, PRIORITY_MAP["high"])

    type_key = case_data.get("type", "functional")
    type_uuid = TYPE_MAP.get(type_key, TYPE_MAP["functional"])

    module_uuid = resolve_module_uuid(case_data, env, override_module)

    # Convert steps to ONES format
    raw_steps = case_data.get("steps", [])
    steps = []
    for s in raw_steps:
        if isinstance(s, dict):
            steps.append({"desc": s.get("desc", ""), "result": s.get("result", "")})
        elif isinstance(s, str):
            steps.append({"desc": s, "result": ""})

    # /items/add silently drops steps; we create the shell first and then
    # use the dedicated testcase update endpoint to persist steps.
    body = {
        "item": {
            "name": case_data["name"],
            "assign": case_data.get("assign", user_id),
            "priority": priority_uuid,
            "type": type_uuid,
            "module_uuid": module_uuid,
            "library_uuid": library_uuid,
            "item_type": "testcase_case",
            "testcase_library": library_uuid,
            "testcase_module": module_uuid,
            "condition": case_data.get("condition", ""),
            "desc": case_data.get("desc") or case_data.get("description", ""),
            "related_wiki_page": [],
        }
    }

    status, resp = api_call("POST", f"/project/api/project/team/{team}/items/add", body, env=env)

    if status == 200 and isinstance(resp, dict) and "item" in resp:
        item = resp["item"]
        case_uuid = item.get("uuid", "")

        # Persist steps via the real testcase update endpoint
        step_ok, step_msg = update_case_steps(case_uuid, case_data, env, override_module)

        return {
            "success": True,
            "uuid": case_uuid,
            "key": item.get("key", ""),
            "name": item.get("name", ""),
            "id": f"T{item.get('number', '')}" if "number" in item else "",
            "steps_written": step_ok,
            "steps_message": step_msg,
        }
    else:
        return {
            "success": False,
            "status": status,
            "error": str(resp)[:300] if isinstance(resp, str) else json.dumps(resp, ensure_ascii=False)[:300],
        }


def add_cases_to_plan(plan_uuid: str, case_uuids: list, env: dict):
    """Add test cases to a test plan."""
    team = env.get("ONES_TEAM_UUID", "T7u1zXum")
    body = {"case_uuids": case_uuids}
    status, resp = api_call(
        "POST",
        f"/project/api/project/team/{team}/testcase/plan/{plan_uuid}/cases/add",
        body, env=env
    )
    if status == 200 and isinstance(resp, dict):
        return {
            "success": True,
            "added": resp.get("success_cases", []),
            "not_found": resp.get("not_found_cases", []),
        }
    return {"success": False, "status": status, "error": str(resp)[:300]}


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def cmd_modules(env, args):
    """List modules in the library."""
    ensure_token(env)
    print(f"Modules in library {env.get('ONES_LIBRARY_UUID', 'XcAFFViB')} (Katana):")
    print("-" * 80)
    modules = get_modules(env)
    for m in modules:
        indent = "  " if m.get("parent", {}).get("uuid") else ""
        count = m.get("testcaseCaseCount", 0)
        default = " (default)" if m.get("isDefault") else ""
        # API path is often a UUID chain; show it only when it looks human-readable.
        path = m.get("path", "")
        path_hint = f"  [{path}]" if path and (" " in path or "/" in path) else ""
        print(f"  {indent}{m.get('name', 'N/A'):40s}  uuid={m.get('uuid', 'N/A'):12s}  cases={count}{default}{path_hint}")
    print(f"\nTotal: {len(modules)} modules")


def cmd_plans(env, args):
    """List test plans."""
    ensure_token(env)
    print("Test plans:")
    print("-" * 80)
    plans = get_plans(env)
    # Show most recent first
    plans.sort(key=lambda p: p.get("create_time", 0), reverse=True)
    for p in plans[:20]:
        name = p.get("name", "N/A")[:60]
        uuid = p.get("uuid", "N/A")
        print(f"  {name:62s}  uuid={uuid}")
    if len(plans) > 20:
        print(f"\n  ... and {len(plans) - 20} more (use --all to see all)")
    print(f"\nTotal: {len(plans)} plans")


def cmd_create(env, args):
    """Create a single test case from JSON file."""
    ensure_token(env)

    with open(args.file, "r", encoding="utf-8") as f:
        case_data = json.load(f)

    print(f"Creating test case: {case_data.get('name', 'N/A')[:60]}")
    if args.module:
        print(f"  (using module override: {args.module})")
    result = create_case(case_data, env, override_module=args.module)

    if result["success"]:
        print(f"  >>> SUCCESS!")
        print(f"  UUID: {result['uuid']}")
        print(f"  Key:  {result['key']}")
        if result.get("id"):
            print(f"  ID:   {result['id']}")
    else:
        print(f"  >>> FAILED (status {result.get('status', '?')})")
        print(f"  Error: {result.get('error', 'N/A')}")
        sys.exit(1)


def cmd_batch(env, args):
    """Batch create test cases from JSON array file."""
    ensure_token(env)

    with open(args.file, "r", encoding="utf-8") as f:
        cases = json.load(f)

    if not isinstance(cases, list):
        print(f"Error: {args.file} must contain a JSON array of cases", file=sys.stderr)
        sys.exit(1)

    print(f"Batch creating {len(cases)} test cases...")
    if args.module:
        print(f"  (using module override for all cases: {args.module})")
    print("=" * 60)

    results = []
    for i, case_data in enumerate(cases, 1):
        name = case_data.get("name", "N/A")[:50]
        print(f"[{i}/{len(cases)}] {name}", end=" ... ")
        result = create_case(case_data, env, override_module=args.module)

        if result["success"]:
            print(f"OK (uuid={result['uuid']}, id={result.get('id', 'N/A')})")
            results.append(result)
        else:
            print(f"FAIL: {result.get('error', 'N/A')[:80]}")
            results.append(result)

        # Rate limit: 500ms between creates
        if i < len(cases):
            time.sleep(0.5)

    print("=" * 60)
    success = sum(1 for r in results if r["success"])
    failed = len(results) - success
    print(f"Done! Success: {success}, Failed: {failed}")

    if failed > 0:
        print("\nFailed cases:")
        for r in results:
            if not r["success"]:
                print(f"  Error: {r.get('error', 'N/A')[:100]}")

    # Save results
    results_path = PROJECT_DIR / "data" / "ones_create_results.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to: {results_path}")


def cmd_add_to_plan(env, args):
    """Add cases to a test plan."""
    ensure_token(env)
    plan_uuid = args.plan_uuid
    case_uuids = args.case_uuids

    print(f"Adding {len(case_uuids)} case(s) to plan {plan_uuid}...")
    result = add_cases_to_plan(plan_uuid, case_uuids, env)

    if result["success"]:
        print(f"  Added: {len(result['added'])}")
        if result["not_found"]:
            print(f"  Not found: {result['not_found']}")
    else:
        print(f"  FAILED: {result.get('error', 'N/A')}")
        sys.exit(1)


def cmd_refresh_token(env, args):
    """Force refresh the ONES auth token."""
    refresh_token_via_playwright()
    print("Token refreshed successfully.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="ONES Test Case Writer — create test cases via ONES REST API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command")

    # create
    p_create = sub.add_parser("create", help="Create a single test case from JSON")
    p_create.add_argument("file", help="Path to case JSON file")
    p_create.add_argument("--module", metavar="UUID", help="Override module_uuid for this case")

    # batch
    p_batch = sub.add_parser("batch", help="Batch create from JSON array file")
    p_batch.add_argument("file", help="Path to JSON array file")
    p_batch.add_argument("--module", metavar="UUID", help="Override module_uuid for all cases in the batch")

    # modules
    sub.add_parser("modules", help="List modules in the Katana library")

    # plans
    p_plans = sub.add_parser("plans", help="List test plans")
    p_plans.add_argument("--all", action="store_true", help="Show all plans (not just recent 20)")

    # add-to-plan
    p_add = sub.add_parser("add-to-plan", help="Add cases to a test plan")
    p_add.add_argument("plan_uuid", help="Test plan UUID")
    p_add.add_argument("case_uuids", nargs="+", help="Case UUID(s) to add")

    # refresh-token
    sub.add_parser("refresh-token", help="Force refresh ONES auth token")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    env = load_env()
    commands = {
        "create": cmd_create,
        "batch": cmd_batch,
        "modules": cmd_modules,
        "plans": cmd_plans,
        "add-to-plan": cmd_add_to_plan,
        "refresh-token": cmd_refresh_token,
    }
    cmd_func = commands.get(args.command)
    if cmd_func:
        cmd_func(env, args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
