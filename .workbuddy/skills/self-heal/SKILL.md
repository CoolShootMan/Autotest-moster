---
name: self-heal
description: Deterministic-first self-healing pipeline for the Katana UI automation suite. After `main` produces an Allure report, ingest the failures, run a diagnostic probe to the failing step, produce deterministic locator diffs (L1, zero AI), route by repair tier (T1 auto-apply / T2 review / T3 escalate), and emit a one-click manifest. Use when the user says "自愈", "self-heal", "用例自愈", "run main then heal", or wants to auto-fix locator-drift failures from a test run. Triggers include "修复失败用例", "heal the broken cases", "生成自愈报告".
agent_created: true
---

# Self-Healing Test Case Pipeline (Katana UI automation)

## Overview

A report-driven, **deterministic-first** pipeline that turns a failed `main` Allure run into concrete, reviewable fixes. It replaces the old "throw every failure at an LLM" approach that wasted tokens and mis-attributed root causes.

Design core (see `.workbuddy/adr-self-healing.md`, ADR-001 Accepted):
- **Deterministic layers eat the cheap fixes first**; AI only runs for the long tail.
- **Repair tier (T1–T3) is orthogonal to heal layer (L0–L4)** and decides *what can be auto-applied*.
- **Anti-false-green is a hard constraint**: an assertion failure with healthy locators is NEVER auto-fixed — it is escalated.

## When to use

- After running `main` (or any pytest run that writes `allure-results/<timestamp>/`) and getting failures.
- Triggers: "自愈", "self-heal", "用例自愈", "跑完 main 帮我修", "heal the broken cases", "生成自愈报告".
- Do **not** use this for writing new cases — that is `jira-ones-testflow` (untouched by this skill).

## Architecture (L0–L4 layers + T1–T3 triage)

| Layer | Mechanism | AI? | Produces |
|---|---|---|---|
| L0 | Flaky rerun guard | no | `FLAKY_CANDIDATE` (probe re-runs to step with no failure) |
| L1 | Deterministic locator/selector re-identification (`heal_locate`) | no | `LocatorDiff` (old→new + confidence + tier) |
| L2 | Causal trace / precondition attribution (`heal_probe` DOM context) | no | root-cause hint (e.g. precondition not met) |
| L3 | Rule classifier (`heal_classify`) | no | `(category, tier, confidence)` |
| L4 | AI long-tail repair (`heal_ai`) | yes (bounded) | hypothesis + YAML diff + confidence |

**Repair tiers (what gets auto-applied):**
| Tier | Definition | Handling | Token |
|---|---|---|---|
| **T1** | locator-only, low risk, confident | **AUTO_APPLY** (manifest, default) | 0 |
| **T2** | action-sequence fix / low-confidence locator | **REVIEW** (apply with `--include-t2`) | 0 or low |
| **T3** | flow/assertion rewrite, needs requirement context | **ESCALATE** (human + Jira-driven) | high (L4) |

**Hard rules (guardrails):**
- Assertion failure + locators resolve fine → `ESCALATE`, never `AUTO_APPLY`. Pure locator healing would falsely pass.
- `data-testid` candidates that are generic MUI classes (`mui-*`, `Private*`) are **rejected** as non-unique.
- Any `data-testid` diff is hard-capped to confidence 0.85 → REVIEW tier (not auto), so narrow `role=button name=...` is preferred when available.
- L4 token budget (default 20/case) gates AI; overflow → `DEFERRED_NEXT_RUN` (queued, never dropped).

## Runtime requirements

Use the **same Python interpreter that runs `main`**. Verified working interpreter:
- **System `D:/Program Files/python.exe` (3.9.8)** — has `pandas 2.3.3` + `pyyaml 6.0.3` + `playwright` + `pytest 7.4.4`. This is the runtime that runs the suite, so use it for `self_heal.py` too (the probe subprocess inherits `sys.executable`).

The managed venv (`C:\Users\tester\.workbuddy\binaries\python\envs\default`) is **NOT** suitable here — it has `playwright` but lacks `pytest` and `pandas` (required transitively by `actions/layout.py` / `actions/form.py`). Do not launch `self_heal.py` with it.

Must have the Playwright Chromium browser installed and a valid storage-state cookie
(`test_case/UI/Test_Katana/cookie_release.json`) for the target environment
(`https://release.pear.us`). Run commands **from the repo root** so relative imports resolve.

## Tools (contract — the skill orchestrates these; do not modify `jira-ones-testflow`)

All under `test_case/UI/Test_Katana/heal/`:

| Tool | I/O | Role |
|---|---|---|
| `heal_parse.py` | `parse_run(run_dir) -> (run_meta, [FailedCase])` | Ingest one Allure run → failed cases (case_id, yaml_path, step_index, err_msg, status, labels). Handles the `subSuite` label quirk (no closing `]`). |
| `heal_probe.py` | `python heal_probe.py <case_id> --step <0-based> --yaml <path> --mode capture --out <json>` | Deterministic diagnostic probe: re-run to the failing step in a real browser, capture DOM context + candidate locators + precondition state. `classify(err, dom_ctx)` returns `(signature, heal_layer, tier, hint)` with the T3 anti-false-green rule. |
| `heal_locate.py` | `heal_locate(ProbeResult) -> LocatorDiff` | L1 deterministic locator re-identification. Anchor priority: `data-testid` > `role+name` > `text` > `position` > `visual`. Outputs `LocatorDiff{old,new,confidence,auto_apply,repair_tier,yaml_patch}`. |
| `heal_classify.py` | `route(sig, tier, confidence, strategy) -> AUTO_APPLY\|REVIEW\|ESCALATE`; `backfill_corpus_tier(path)` | Deterministic routing + corpus triage backfill. |
| `heal_ai.py` | `heal_ai(ctx) -> {root_cause_hypothesis, yaml_patch?, confidence, needs_human_review}` | L4 long-tail. Deterministic fallback always runs (no key needed); LLM only if `HEAL_AI_KEY` set. `fetch_requirement(ticket)` reads Jira via `tools/jira_reader`. |
| `heal_apply.py` | `apply_manifest(manifest, include_t2, dry_run) -> (applied, skipped)` | One-click apply. Writes `.heal_bak` backup before each edit. |
| `self_heal.py` | orchestrator (see CLI below) | Ties it together; writes `heal_report.{json,md}` + `heal_manifest.json`. |

## The flow (step by step)

1. **Generate the report.** Run `main` (your normal pytest + Allure). This writes
   `allure-results/<timestamp>/`.
2. **Heal.** From repo root:
   ```bash
   python test_case/UI/Test_Katana/heal/self_heal.py --run allure-results/<timestamp> --out test_case/UI/Test_Katana/heal/report
   ```
   Useful flags: `--limit N` (first N failures, for testing), `--case <id>` (one case),
   `--no-ai` (deterministic only), `--dry-run` (don't write manifest).
3. **Review.** Open `heal/report/heal_report.md`:
   - `AUTO_APPLY` = safe locator fix, will apply automatically.
   - `REVIEW` = needs a human glance (T2 / low-confidence / data-testid candidate).
   - `ESCALATE_AI` / `DEFERRED_NEXT_RUN` = flow/assertion regression; read the hypothesis, decide manually.
   - `FLAKY_CANDIDATE` = probe reached the step fine → likely timing/flaky, not a real defect.
4. **Apply.** (Make a git commit/backup first.)
   ```bash
   python test_case/UI/Test_Katana/heal/self_heal.py --apply                 # T1 only
   python test_case/UI/Test_Katana/heal/self_heal.py --apply --include-t2    # also T2
   ```
   Add `--dry-run` to preview the YAML edits. Each applied file gets a `.heal_bak` backup.
5. **Verify.** Re-run `main` on the touched cases to confirm the green is real (not false).

## Corpus & cross-version learning

- Ground truth: `.workbuddy/self-healing/heal_corpus.json` (real fixed cases from the storefront refactor). Each entry carries `failure_signature`, `real_root_cause`, `heal_layer`, `auto_healable`, and (after backfill) `repair_tier`.
- Backfill the derived `repair_tier` field if the corpus changes:
  ```bash
  python test_case/UI/Test_Katana/heal/heal_classify.py --corpus .workbuddy/self-healing/heal_corpus.json
  ```
- The probe (`heal_probe`) is designed to grow this corpus automatically at runtime (each run emits a structured `probe_result`), so the system gets more accurate over versions.

## Gotchas / known quirks

- **Allure label quirk:** the `subSuite` label value ends with `[` and no closing `]` (e.g. `test_case[All_YAML/Post/Post_setting.yaml`). `heal_parse.yaml_path_from_labels` matches on the opening bracket only.
- **L1 real action surface:** this framework's action engine has loose matching (CI `role+name` + text fallback), so *pure name text drift rarely fails in-suite*. L1 external self-heal's real value is **structural displacement / `data-testid` changes / broken `locator:` CSS**, not name typos.
- **T3 is not autonomously decidable:** without a reference correct case or the Jira requirement, the tool cannot confirm a flow change — it routes to ESCALATE with a structured hypothesis instead of guessing. This is by design.
- Probe runs use the same `sys.executable` that launched `self_heal.py`, so always launch `self_heal.py` with the full-stack Python.
