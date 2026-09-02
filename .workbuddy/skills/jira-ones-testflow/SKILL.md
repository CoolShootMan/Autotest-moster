---
name: jira-ones-testflow
description: Onboard test cases and a test plan from a Jira ticket into the ONES test management platform, then backfill the ONES plan link into the Jira ticket. Use this skill when the user wants to create/record test cases in ONES for a Jira ticket (e.g. KAT-XXXX), build a test plan, link cases to the plan, and fill the plan URL back into Jira. Triggers include "录入测试用例", "创建测试计划", "把用例录到 ONES", "回填 Jira 测试链接", "test case onboarding", "ONES test plan".
agent_created: true
---

# Jira → ONES Test Onboarding Flow

## Overview

End-to-end pipeline that turns a Jira ticket (e.g. `KAT-11397`) into a fully populated ONES test plan: read the requirement from Jira, generate test cases, create them via the ONES REST API, create a test plan via UI automation, link the cases to the plan via API, and backfill the ONES plan URL into the Jira ticket's `Test Case Link for QA` field. The pipeline is project-specific and depends on the tools already present in this repo.

## Prerequisites

- Managed Python venv `C:\Users\tester\.workbuddy\binaries\python\envs\default\Scripts\python.exe` with `playwright` installed. If it is missing deps, install them with:
  ```
  C:\Users\tester\.workbuddy\binaries\python\versions\3.13.12\python.exe -m venv C:\Users\tester\.workbuddy\binaries\python\envs\default
  C:\Users\tester\.workbuddy\binaries\python\envs\default\Scripts\python.exe -m pip install playwright
  C:\Users\tester\.workbuddy\binaries\python\envs\default\Scripts\python.exe -m playwright install chromium
  ```
- Run from the repo root so relative paths resolve.

### Credential setup (first-time onboarding)

All credentials live in `backend/.env`. They fall into two groups:

**Personal credentials** (each teammate uses their own — the agent should ask for these interactively on first run):
| Field | How to obtain |
|-------|---------------|
| `JIRA_EMAIL` | The teammate's Jira login email |
| `JIRA_API_TOKEN` | Atlassian → Profile → **Security → API tokens → Create API token** (shown once) |
| `ONES_EMAIL` | The teammate's ONES login email |
| `ONES_PASSWORD` | The teammate's ONES login password |
| `FIGMA_TOKEN` | Figma → Avatar → **Settings → Personal access tokens → Generate new token**; select only `file_content:read` and `file_metadata:read` |

`ONES_AUTH_TOKEN` does **not** need manual entry — `ones_writer.py refresh-token` logs in with email+password and writes it automatically.

**Team-shared constants** (same for everyone — copy verbatim):
```
JIRA_BASE_URL=https://pearshop.atlassian.net
ONES_URL=https://sz.ones.cn
ONES_ORG_UUID=ATfPf79v
ONES_TEAM_UUID=T7u1zXum
ONES_LIBRARY_UUID=XcAFFViB
ONES_PRIORITY_HIGHEST=3g7bLpa1
ONES_PRIORITY_HIGH=VRXHXgbp
ONES_PRIORITY_NORMAL=JoEcqaCe
ONES_PRIORITY_LOW=R7wMSiP3
ONES_PRIORITY_LOWEST=3DvJC11V
ONES_TYPE_FUNCTIONAL=7qLS7W5f
```

`ONES_USER_ID` is personal but auto-discovered — after the first `refresh-token` run, read it from the login response and backfill into `.env`.

**Agent behaviour on first run**: Before Step 1, check whether `backend/.env` exists and contains the personal credentials. If any are missing, **stop and ask the user** for their Jira email, Jira API token, ONES email, ONES password, and Figma token, then write all fields (personal + team constants) into `backend/.env` and run `ones_writer.py refresh-token`. Do not proceed until credentials are in place. The user only needs to provide a Jira ticket link — the agent handles the rest.

## Pre-flight Hard Rules (must obey — these were learned from real incidents)

These rules come from KAT-11830 and earlier tickets. Breaking any of them leads to silent regressions in ONES or Jira.

1. **Pure-English content for ONES test cases.** The platform is English-only end to end (ONES UI/DB, Jira UI, GitHub, internal docs). Every name / desc / condition / step-desc / step-result written to ONES must be English. This includes module names, titles, preconditions, descriptions — no Chinese characters anywhere in `data/<TICKET>_test_cases.json` or anything that flows into ONES. (KAT-11830 incident, 2026-08-04: the AI generated Chinese cases despite knowing the system was English, and the user had to ask for a re-translate push — never again.) The Chinese草稿 file `data/KAT-11830_No7_test_cases_draft.md` is fine as an offline worksheet, but the JSON that hits ONES is English. The Chinese草稿 must NEVER become the JSON.
2. **Jira backfill is part of the same flow — never leave it for the user.** Step 5 (`ones_create_plan_v3.py`) returns the plan UUID at the very end of its run. The agent must immediately capture that UUID and run `python tools/jira_backfill_test_link.py <TICKET> <PLAN_UUID>`. Returning to the user without backfilling is a defect. (KAT-11830 incident again: the plan finished in the background, the agent reported "计划正在后台创建" and stopped, then the user had to ask "为什么不回填 Jira?" — that is not what an automation skill does.)
3. **Real ones_writer.py field contract, not the docs.** `ones_writer.create_case` reads **name** / **desc** (or `description` — both accepted since 2026-08) / **condition** / **steps** (each step: `desc` + `result`) / **priority** (`"highest"` = P0, `"high"` = P1). The older doc keys `title` / `precondition` / `expect` / `P0` / `P1` are outdated — copy a known-good case from `data/<existing_ticket>_test_cases.json` if unsure. **KAT-11814 incident (2026-08-27): the JSON used `description` while the code read only `desc`; `case_data.get("desc", "")` silently produced an empty string and 31/31 cases landed in ONES with blank descriptions.** After Step 3, always verify `desc` is non-empty via GraphQL, not just that the create call returned success.
4. **The 15-tool-call rule for skill housekeeping.** After any flow that touches ≥3 ONES calls (  batch / link / verify / update), do the bookkeeping once at the end: delete temp probe scripts in `tools/_*.py`, save any new stable utility (e.g. `jira_backfill_test_link.py`) to `tools/`, append a bullet to today's memory file.

5. **E2E scenario-level granularity for test cases (KAT-11814 incident, 2026-08-28).** Write cases at the **business-scenario / end-to-end** level, not the component / interaction level. ONE case = ONE user journey or ONE business rule, with all the intermediate UX steps (open page, click Apply, "Thanks" popup, click "Got it", land back on post) captured as *steps inside that single case* — NOT as separate cases. Do NOT split "toggle ON saves" and "toggle OFF restores" into two cases, nor "click Apply shows popup" and "click Got it closes popup" into two cases. KAT-11814 was first drafted at 31 cases (component-level: "click X jumps to Y", "toggle on", "toggle off" each its own case); the user rejected this as fragmented and it was merged down to 12 E2E scenario-level cases. The reference baseline for this project's granularity is the T-Mobile quota subsystem (13 cases covering the entire subsystem at scenario level, e.g. "asynchronously reclassified", "global shared pool blocking at 10000 segments"). **If the draft exceeds ~15 cases for a single ticket, STOP and confirm granularity with the user via AskUserQuestion before creating anything in ONES** — do not assume the user wants fine-grained cases.

## Field & UUID Reference

See `references/ones_jira_reference.md` for the authoritative list of ONES UUIDs, priority map, Jira custom field IDs, and UI selectors. Load it whenever exact IDs are needed.

## Workflow

### Step 1 — Read the Jira requirement

```
"C:/Users/tester/.workbuddy/binaries/python/envs/default/Scripts/python.exe" tools/jira_reader.py KAT-11397 --format text
```

Extract: summary (becomes the test plan title suffix), description (test case source), and `QA` field (`customfield_10083`) — the QA person becomes the test plan owner.

### Step 1.5 — Analyse Figma designs (for large/complex tickets)

If the Jira description contains a Figma link, **always** pull the design via the Figma REST API before writing cases. Do not rely solely on the Jira text — UI details (button labels, field order, error states) live in Figma.

```
"C:/Users/tester/.workbuddy/binaries/python/envs/default/Scripts/python.exe" tools/figma_api_reader.py --url "<FIGMA_URL>" --output data/figma_<TICKET> --analyze
```

`figma_api_reader.py`:
- Extracts the full node tree and all text content from the Figma file.
- Downloads high-resolution PNGs of key screens in batches (5–7 nodes per request to respect API limits).
- Writes a structured analysis (`analysis.md`) with user flows, key screens, and suggested test-case categories.

**Required token**: `FIGMA_TOKEN` in `backend/.env` with `file_content:read` and `file_metadata:read` permissions only.

**Fallback**: If the Figma API is unavailable, ask the user to screenshot the key screens (one per user scenario) and describe them.

### Step 1.6 — Record open questions and validate with the user

Before generating cases, the agent must explicitly list:
1. The user scenarios it identified from Jira + Figma.
2. The module it intends to use in ONES (see Step 2).
3. Any unclear requirements, missing edge cases, or contradictory information.

**Do not proceed to Step 2 until the user confirms or answers**. This prevents rework. Example:

> "I see two Collabs modules in ONES: `Collabs` under My Shop (53 cases) and top-level `Collabs` (4 cases). KAT-11654 is about the co-seller invitation flow, so I plan to use the My Shop → Collabs module (`3pfH7pm8`). Please confirm."

### Step 2 — Generate test cases

Analyse the Jira description and Figma analysis and draft `data/<TICKET>_test_cases.json`. Each case uses the **real `ones_writer.create_case` field contract** (not the older doc keys):

```json
{
  "name": "Verify ...",
  "desc": "Scenario description (English)",
  "condition": "Preconditions (English)",
  "steps": [{"desc": "...", "result": "..."}],
  "priority": "highest" | "high",
  "module_uuid": "<module UUID>"
}
```

  (`description` is also accepted as an alias for `desc` since the 2026-08 fix. The older doc keys `title` / `precondition` / `expect` / `P0` / `P1` are outdated — `create_case` will silently ignore them. P0 maps to `"highest"`, P1 maps to `"high"`.)

#### Test Case Design Methodology — E2E scenario-level (MANDATORY)

Write cases the way this project's QA engineers write them: **one case per real user journey or business rule**, with the granular UX interactions as *steps* inside the case, not separate cases. This is Pre-flight Rule 5 — read it first.

**Do this (✅ E2E scenario-level):**
- A config case covers the toggle + expiration options + email template together as one scenario: *"Organizer configures the approval framework (toggle ON, expiration 24/48/72h, email template) and it takes effect everywhere"*.
- A single-apply case covers: post page CTA → click Apply → "Thanks for your submission!" popup → click "Got it" → returns to post page. All of it = ONE case, ~5 steps.
- A mixed-cart case covers: checkout notices "These items require approval" → submit → non-approval items still checkout normally.

**Do NOT do this (❌ component-level fragmentation — rejected on KAT-11814):**
- "Verify toggle is OFF by default" as its own case AND "Verify toggling it ON saves" as its own case AND "Verify toggling it OFF restores" as its own case.
- "Verify popup appears on Apply" as one case AND "Verify clicking Got it closes popup" as one case.
- Any "click X → navigates to Y" expressed as an isolated case.

**Granularity decision rule:**
- If a sequence of actions is a single uninterrupted user flow, it is ONE case (with multiple steps).
- Split ONLY when the paths are genuinely independent UX routes or independent edge cases — e.g. "unauthenticated user hits login gate", "organizer revokes approval before use", "duplicate application blocked". These deserve their own case because they are not part of the main happy path.
- **Hard stop**: if the draft reaches ~15 cases for one ticket, pause and confirm the intended granularity with the user before writing to ONES. Do not silently produce 30+ component-level cases.

**Reference files** (canonical examples of the target granularity — read them before drafting):
- `data/KAT-11814_test_cases.json` — the merged 12-case E2E version (was 31 component-level before merge).
- The T-Mobile quota suite (13 cases) — covers the entire subsystem at scenario level.

**Module selection** (must be decided per ticket — never hardcode):
- Run `python tools/ones_writer.py modules` to list all modules with their full paths.
- Pick the module that matches the ticket's feature area (e.g. Collabs → My Shop → Collabs).
- Set `ONES_DEFAULT_MODULE_UUID=<uuid>` in `backend/.env` **temporarily for this ticket**, or pass `--module <uuid>` to `ones_writer.py batch`, or set `module_uuid` on each case in the JSON.
- If unsure, ask the user before creating cases.

Only use **P0 and P1** priorities (user convention). Map to ONES priority UUIDs via the reference file.

### ⛔ CRITICAL — Modifying existing cases (T4101 incident, 2026-07-22)

When a ticket's feature is "copied" to a new flow (e.g. post preferences appear both in Collabs settings AND invite acceptance flow):

1. **FETCH + backup before modifying.** Before any modification:
   - FETCH the current case detail (name, condition, assign, steps) via GraphQL
   - Save a backup to `data/<TICKET>_case_backup_<UUID>.json`
   - Only then modify — outdated steps CAN be overwritten when the flow has genuinely changed, but do it deliberately, never accidentally

2. **NEVER change the assignee.** The `assign` field must be preserved from the original case. Do not set it to the current user unless explicitly told to.

3. **If the feature exists in its original module, do NOT modify that case.** Instead:
   - Create a NEW case in the new flow's module (or the ticket's module)
   - Reference the original case's steps as a guide
   - The original case stays untouched — the feature was not removed from its original location

4. **For "modify existing case" tasks:** clearly distinguish between:
   - "Update title + ADD steps" (append only) — the default
   - "Update title + REPLACE steps" (full overwrite) — only when the user explicitly says the entire flow changed

**Title naming convention**:
- Do NOT prefix case titles with the ticket number or internal tracking IDs (e.g. `KAT-11397 T1:`).
- Start the title with a clear action verb, preferably **`Verify ...`** (e.g. `Verify redirect URL works after form submission`, `Verify invalid redirect URL format is rejected`). This makes the test intent immediately obvious, matching the T5506 style in ONES.
- Keep it concise and scenario-focused.

### Step 3 — Create cases in ONES (REST API)

```
"C:/Users/tester/.workbuddy/binaries/python/envs/default/Scripts/python.exe" tools/ones_writer.py batch data/<TICKET>_test_cases.json
```

**Input format**: the file must be a **pure JSON array** of case objects — NOT a `{"cases": [...]}` wrapper. A wrapped object aborts with `must contain a JSON array of cases`.

Creates cases under the target module. Results (with new UUIDs) are written to `data/ones_create_results.json`.

To override the module for the whole batch (e.g. when `ONES_DEFAULT_MODULE_UUID` is not set and the JSON lacks `module_uuid`):
```
"C:/Users/tester/.workbuddy/binaries/python/envs/default/Scripts/python.exe" tools/ones_writer.py batch data/<TICKET>_test_cases.json --module <MODULE_UUID>
```

**Steps are written in a separate call**: ONES `items/add` silently ignores the `steps` field (and `testcase_case_steps: []` in the body will clear them). `ones_writer.py` handles this automatically — after `items/add` returns the new UUID, it calls the correct endpoint:
```
POST /project/api/project/team/{team}/testcase/library/{library_uuid}/cases/update
```
with a `cases[]` body containing `steps[]` (each step: `desc`, `result`, `index`, `key`, `testcaseCase: {uuid}`, `uuid`). If steps are ever missing, run `tools/ones_update_steps.py` to batch-write them.

### Step 3.5 — Verify steps persisted (MANDATORY, do NOT skip)

**This step is non-negotiable.** The ONES REST `cases/update` endpoint can return `errcode: "OK"` even when steps silently failed to persist. This has happened twice (KAT-11397 and KAT-11654) — the `ones_create_results.json` reported `steps_written: true` for all cases, but ONES showed 0 steps.

After Step 3 (and again after Step 4 if steps were re-written), run a GraphQL query to verify every case has steps:

```python
from ones_writer import load_env, graphql

env = load_env()
# Collect all case UUIDs from ones_create_results.json + any modified existing cases
case_uuids = [...]  # all UUIDs to verify

query = """
query VerifySteps($filter: testcaseCaseStepsFilter) {
  testcaseCaseSteps(filter: $filter) {
    testcaseCase { uuid }
    desc
    result
    index
  }
}
"""
variables = {"filter": {"testcaseCase_in": case_uuids}}
status, res = graphql(query, variables, env)

# Group steps by case UUID
steps_by_case = {}
for step in res["data"]["testcaseCaseSteps"]:
    case_uuid = step["testcaseCase"]["uuid"]
    steps_by_case.setdefault(case_uuid, []).append(step)

# Verify every case has at least 1 step
missing = [uuid for uuid in case_uuids if uuid not in steps_by_case]
if missing:
    print(f"❌ {len(missing)} cases have 0 steps: {missing}")
    # RE-WRITE steps for these cases immediately, then re-verify
else:
    print(f"✅ All {len(case_uuids)} cases have steps")
    for uuid, steps in steps_by_case.items():
        print(f"  {uuid}: {len(steps)} steps")
```

**Key details**:
- The GraphQL field is `testcaseCaseSteps` with filter `testcaseCase_in` — NOT a nested field inside `testcasePlanCases` (that doesn't work).
- The REST `cases?uuid=X` endpoint returns ALL cases in the library (4600+) and is unreliable for step verification — always use GraphQL.
- If any case has 0 steps, re-run `update_case_steps` for those cases and verify again. Do not proceed to plan creation until all cases pass.
- Save the verification result to `data/<TICKET>_step_verification.json` as proof.

### Step 4 — Verify case priorities (they are set at creation)

`ones_writer.py` sets the priority in the `items/add` body during Step 3, and **this works** — verified on KAT-11814 (19 P0 + 12 P1 all landed correctly). No separate priority-setting call is needed.

**Do NOT use the standalone REST `cases/update` endpoint with the old example body** (uuid + library_uuid + module_uuid + name + assign + type + priority + ...). As of 2026-08 that shape fails with `MissingParameter.TestCase.Module` even when `module_uuid` is present — the schema has changed. The only known-good way to invoke `cases/update` is the exact body `ones_writer.update_case_steps()` builds (uuid, name, condition, desc, library_uuid, module_uuid, assign, type, priority, steps — all fields present).

To verify priorities after batch creation, query GraphQL `testcaseCaseSteps` (same query as Step 3.5) with the `testcaseCase { uuid name desc condition }` projection plus a priority check via the REST `cases?uuid=X` listing, or spot-check 2–3 cases in the ONES UI. P0=`3g7bLpa1` (highest), P1=`VRXHXgbp` (high). Only use P0/P1 for this project.

### Step 5 — Create the test plan (UI automation)

```
"C:/Users/tester/.workbuddy/binaries/python/envs/default/Scripts/python.exe" tools/ones_create_plan_v3.py <TICKET> --owner <OWNER_QUERY> [--date YYYY-MM-DD]
```

**Parameters**:
- `<TICKET>` — the Jira ticket key (e.g. `KAT-11397`), used to fetch the summary (becomes plan name), QA owner, and execution date.
- `--owner <OWNER_QUERY>` — the search term to type into the ONES owner dropdown. Derive this from the Jira QA field's `displayName`: take the **first name in lowercase** (e.g. `"Yuxiao Zhu"` → `"yuxiao"`). This must be unique enough to match exactly one person in the dropdown.
- `--plan-name` (optional) — override the auto-generated `"TICKET: <jira summary>"` plan name.
- `--date` (optional) — override execution date (default: automatically extracted prioritizing Jira Description `due: Month DD, YYYY`, fallback to Jira native `duedate` field, or today).

`ones_create_plan_v3.py` implements:
- Fetches the Jira summary, QA displayName, and execution due date automatically.
- Sets the **test phase to 功能测试** (not the default 冒烟测试).
- Sets execution date from Jira Description (lead-defined due date), falling back to native `duedate` or today.
- Saves the plan, extracts the new plan UUID, and links cases via API.
- Owner selection: types the query, then **only clicks the option that contains the query string** — never falls back to "first option". If no match, raises an error.

ONES has **no API to create a test plan** (no `createTestcasePlan` GraphQL mutation; REST `items/add` with `item_type=testcase_plan` returns 500). UI automation is the only path.

UI entry: `https://ones.cn/project/#/testcase/team/<TEAM>/index` → click 「新建测试计划」.

### Step 6 — Link cases to the plan (API)

`ones_create_plan_v3.py` auto-links cases from `data/ones_create_results.json` (newly created cases only). If you also modified existing cases, link them separately:
```
"C:/Users/tester/.workbuddy/binaries/python/envs/default/Scripts/python.exe" tools/ones_writer.py add-to-plan <PLAN_UUID> <CASE_UUID>...
```
Uses the `addTestcasePlanCase` GraphQL mutation.

### Step 7 — Backfill Jira

ONES UI URL is auto-captured in `data/ones_create_plan.json` (or printed by `ones_create_plan_v3.py` as `https://ones.cn/project/#/testcase/team/<TEAM>/plan/<PLAN_UUID>/library`). PUT it into Jira's `Test Case Link for QA` field (`customfield_10090`, string) using the dedicated tool:

```
"C:/Users/tester/.workbuddy/binaries/python/envs/default/Scripts/python.exe" tools/jira_backfill_test_link.py <TICKET> <PLAN_UUID>
```

The tool reads `JIRA_EMAIL` / `JIRA_API_TOKEN` from `backend/.env` (already configured for this repo), issues `PUT /rest/api/3/issue/<TICKET>` with `{"fields": {"customfield_10090": "<ONES_PLAN_URL>"}}`, then immediately re-fetches the field to verify. Success: HTTP 204 + MATCH. Failure: HTTP error or MISMATCH (exit 1).

**Do not let the user ask for this step.** Treat `ones_create_plan_v3.py` finishing as the trigger to backfill right then and there. If something blocks backfill (token expired, Jira down, etc.), report the cause explicitly — never silently leave the field empty.

### Step 8 — Final verification (manual spot-check)

After the full pipeline, do a quick visual check in ONES and Jira:
- **ONES case language**: Pure English throughout (Pre-flight Rule 1). Random-sample 2–3 cases via `cases`/`uuid=<X>` endpoint and assert the response contains no characters in `\u4e00`–`\u9fff`. If it does, the JSON was Chinese — translate and re-push via `update_case_steps` (it accepts new name/desc/condition in the body too).
- **ONES**: Open the test plan, verify all cases are linked, priorities are correct, and each case has steps with expected results.
- **ONES case titles**: Confirm titles start with `Verify ...` (or another clear action verb) and contain no internal tracking prefixes (`KAT-XXXX TN:`).
- **Jira**: Confirm the `Test Case Link for QA` field shows the correct ONES plan URL (it was just backfilled in Step 7; quick re-fetch should match).

## Critical Constraints & Pitfalls

- **Priority map is P0/P1 only** for this project. Do not use P2–P4.
- **Plan owner = Jira QA**, never hardcode or default to the first dropdown option. The `--owner` flag must be derived from the Jira QA field's displayName (first name, lowercase).
- **Module must be selected per ticket**: never reuse a historical module UUID (e.g. `2ojXUdsv`) by default. List modules, choose the one matching the feature area, and set `ONES_DEFAULT_MODULE_UUID` or use `--module`.
- **No hardcoded credentials**: all email/password/token values must come from `backend/.env`. Never hardcode personal credentials in source files.
- **Test phase = 功能测试** for ticket-driven plans, not 冒烟测试.
- ONES API domain is `sz.ones.cn` for REST, but the UI workspace is `ones.cn/project/#/...`. Do not confuse the two.
- Token expires ~1h; refresh with `python tools/ones_writer.py refresh-token` (uses Playwright login).
- ONES UI uses `ones-` class prefix (not `ant-`): `.ones-user-select`, `.ones-picker`, `.ones-select`.
- `updateTestcaseCase` requires `key: "testcase_case-<UUID>"` format, not bare `uuid`.
- Use the managed Python venv (`C:\Users\tester\.workbuddy\binaries\python\envs\default\Scripts\python.exe`) for all scripts. If it lacks `playwright`, install via the managed runtime (see Prerequisites).
- **Steps API**: `items/add` silently drops `steps`; use `cases/update` REST endpoint instead. `ones_writer.py` does this automatically; `ones_update_steps.py` can fix missing steps retroactively.
- **Silent empty fields**: `case_data.get(key, "")` never raises on a missing/misspelled key — a wrong field name (e.g. `description` vs `desc` before the alias fix) produces empty strings in ONES with `success: true`. Always re-read created cases from ONES via GraphQL and assert `desc` / `condition` are non-empty, the same way Step 3.5 asserts steps exist.
- **Point conservation**: Simple manual operations (editing a title, changing a dropdown) are cheaper for the user to do by hand than for the agent to automate. Reserve agent work for API calls, batch operations, and tasks requiring code.

## Cleanup

Temporary probe scripts (`tools/_*.py`) accumulate during exploration. After a ticket's flow is complete, delete them; only stable tools (without the `_` prefix) should remain.
