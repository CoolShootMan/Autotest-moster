#!/usr/bin/env python3
"""Backfill ONES plan URL into Jira ticket's customfield_10090 (Test Case Link for QA).

Usage: python tools/jira_backfill_test_link.py <TICKET> <PLAN_UUID>
Reads credentials from backend/.env. Returns exit 0 on 204, writes nothing else.
"""
import os, sys, base64, json, urllib.request, urllib.error

ENV_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", ".env")
TEAM_UUID_DEFAULT = "T7u1zXum"


def load_env():
    env = {}
    with open(ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def build_plan_url(team_uuid, plan_uuid):
    return f"https://ones.cn/project/#/testcase/team/{team_uuid}/plan/{plan_uuid}/library"


def main():
    if len(sys.argv) < 3:
        print("Usage: jira_backfill_test_link.py <TICKET> <PLAN_UUID>")
        sys.exit(2)
    ticket = sys.argv[1]
    plan_uuid = sys.argv[2]
    env = load_env()
    email = env.get("JIRA_EMAIL")
    token = env.get("JIRA_API_TOKEN")
    base = env.get("JIRA_BASE_URL", "https://pearshop.atlassian.net")
    team = env.get("ONES_TEAM_UUID", TEAM_UUID_DEFAULT)
    if not email or not token:
        print("Missing JIRA_EMAIL or JIRA_API_TOKEN in backend/.env")
        sys.exit(2)
    plan_url = build_plan_url(team, plan_uuid)
    print(f"Plan URL: {plan_url}")
    auth = base64.b64encode(f"{email}:{token}".encode()).decode()

    # 1) PUT
    put = urllib.request.Request(
        f"{base}/rest/api/3/issue/{ticket}",
        data=json.dumps({"fields": {"customfield_10090": plan_url}}).encode(),
        method="PUT",
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(put) as r:
            print(f"PUT status: {r.status}")
            if r.status != 204:
                print(r.read()[:300])
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()[:300]}")
        sys.exit(1)

    # 2) Verify
    get = urllib.request.Request(
        f"{base}/rest/api/3/issue/{ticket}?fields=customfield_10090",
        headers={"Authorization": f"Basic {auth}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(get) as r2:
        res = json.loads(r2.read())
        cur = res.get("fields", {}).get("customfield_10090", "<empty>")
        print(f"Verify customfield_10090: {cur}")
        if cur != plan_url:
            print("MISMATCH")
            sys.exit(1)
        print("MATCH")


if __name__ == "__main__":
    main()
