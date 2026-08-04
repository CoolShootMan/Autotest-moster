"""
self_heal.py - Self-healing orchestrator (the self-heal skill's engine).

Pipeline (deterministic-first, AI-last):
  parse (allure report) -> [L0 flaky rerun] -> per failed case:
      heal_probe (capture DOM at failure step)
      -> heal_locate (L1 deterministic locator diff)
      -> heal_classify (route T1/T2/T3)
      -> T1 confident  : AUTO_APPLY (manifest)
         T2             : REVIEW (manifest, apply only with --include-t2)
         T3/UNKNOWN/assertion : heal_ai (L4) -> hypothesis + escalate
  token budget gates L4; overflow deferred to next run (never dropped)
  outputs: heal_report.json + heal_report.md + heal_manifest.json (one-click)

One-click apply:  python self_heal.py --apply [--include-t2]

Triage (instant, no browser):  python self_heal.py --run <ts> --fast
Heavy probe (browser per case): python self_heal.py --run <ts> [--heavy]
  -> for large batches run --heavy in a STANDALONE terminal; progress in heal_progress.log
"""
from __future__ import annotations

import sys
import os
import json
import subprocess
import argparse

HERE = os.path.abspath(__file__)
HEAL_DIR = os.path.dirname(HERE)                        # .../Test_Katana/heal
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HEAL_DIR))))  # .../Autotest-monster
if REPO_ROOT not in sys.path:
    sys.path.append(REPO_ROOT)

from test_case.UI.Test_Katana.heal.heal_parse import parse_run  # noqa: E402
from test_case.UI.Test_Katana.heal.heal_probe import ProbeResult  # noqa: E402
from test_case.UI.Test_Katana.heal.heal_locate import heal_locate  # noqa: E402
from test_case.UI.Test_Katana.heal.heal_classify import route, classify_failure  # noqa: E402
from test_case.UI.Test_Katana.heal.heal_apply import apply_manifest  # noqa: E402
from test_case.UI.Test_Katana.heal.heal_ai import heal_ai, fetch_requirement  # noqa: E402

AI_BUDGET = 20  # max L4 AI calls per run
PROBE_TIMEOUT = 150  # hard cap per-case browser probe (seconds); one bad case can't hang the pipeline
HEAVY_WARN_THRESHOLD = 12  # above this, a browser probe run needs --heavy (or use --fast)


def _write_progress(out_dir: str, rec: dict):
    """Append one line per case so progress is visible even if the UI lags."""
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, "heal_progress.log")
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"{rec['case_id']}\t{rec.get('action')}\t{rec.get('failure_signature')}\t"
                f"{str(rec.get('root_cause', ''))[:140]}\n")


def run_probe(case_id: str, step_index_1based: int, yaml_path: str) -> dict | None:
    """Invoke heal_probe as a subprocess; return probe_result dict or None."""
    out = os.path.join(HEAL_DIR, f"temp_probe_{case_id}.json")
    cmd = [sys.executable, os.path.join(HEAL_DIR, "heal_probe.py"),
           case_id, "--step", str(max(0, step_index_1based - 1)),
           "--yaml", yaml_path, "--mode", "capture", "--out", out]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=PROBE_TIMEOUT)
        return json.load(open(out, encoding="utf-8"))
    except subprocess.TimeoutExpired:
        print(f"  [probe TIMEOUT] {case_id}: exceeded {PROBE_TIMEOUT}s, skipping (no hang)")
        return None
    except Exception as e:
        print(f"  [probe ERROR] {case_id}: {e}")
        return None
    finally:
        if os.path.exists(out):
            os.remove(out)


def process_case(fc: dict, budget: dict, fast: bool = False) -> dict:
    """Run L1-L4 for one failed case; return a result record.

    fast=True: NO browser. Classify purely from the error signature (instant triage).
    """
    case_id = fc["case_id"]
    yaml_path = fc["yaml_path"]
    step_idx = fc["step_index"]
    rec = dict(fc)
    rec["action"] = "UNKNOWN"

    # cheap pre-classify from error text alone (no browser)
    pre_sig, pre_layer, pre_tier, pre_hint = classify_failure(fc["err_msg"], {})

    if fast:
        # instant bucket: no browser, no healing — just tell the user where it lands
        rec["failure_signature"] = pre_sig
        rec["repair_tier"] = pre_tier
        if pre_sig == "assertion":
            rec["action"] = "ESCALATE_AI"
            rec["root_cause"] = "assertion failed; needs Jira/requirement to judge (fast mode: no browser)"
        else:
            rec["action"] = "REVIEW"
            rec["root_cause"] = (pre_hint
                                 + " | fast mode: run WITHOUT --fast (browser probe) to find candidate / confirm flaky")
        return rec

    # lazy probe: assertion failures are always escalate — no browser re-run needed
    if pre_sig == "assertion":
        rec["failure_signature"] = "assertion"
        rec["repair_tier"] = pre_tier
        rec["action"] = "ESCALATE_AI"
        rec["root_cause"] = ("assertion failed while target locators present -> flow/requirement "
                             "regression; no browser probe needed")
        return rec

    probe = run_probe(case_id, step_idx, yaml_path)
    if probe is None:
        rec["action"] = "PROBE_ERROR"
        rec["root_cause"] = "diagnostic probe failed to run (see logs)"
        return rec

    # L0-flaky signal: probe reached the step with no failure -> likely flaky/timing
    if probe.get("failure_signature") == "none":
        rec["action"] = "FLAKY_CANDIDATE"
        rec["root_cause"] = "probe re-ran to the step without failure -> likely flaky/timing, not a real defect"
        rec["repair_tier"] = "T1"
        return rec

    # refine classification with live DOM (target_resolved)
    dom_ctx = probe.get("dom_context", {})
    sig, layer, tier, hint = classify_failure(fc["err_msg"], dom_ctx)
    rec["failure_signature"] = sig
    rec["heal_layer_suggestion"] = layer
    rec["repair_tier"] = tier

    # L1 deterministic locator self-heal
    pr = ProbeResult(
        case_id=case_id, failed_step=probe.get("failed_step", fc["failed_step_key"]),
        failure_signature=sig, original_locator=probe.get("original_locator"),
        dom_context=dom_ctx)
    diff = heal_locate(pr)

    if "new" in diff:  # locator diff produced
        rec["root_cause"] = diff.get("reason", "locator drift")
        rec["proposed_fix"] = diff.get("yaml_patch")
        rec["confidence"] = diff.get("confidence")
        rec["repair_tier"] = diff.get("repair_tier", tier)
        decision = route(sig, rec["repair_tier"], diff.get("confidence", 0), diff.get("strategy"))
        rec["action"] = decision
        # include both AUTO_APPLY and REVIEW diffs in the manifest so --include-t2
        # can apply reviewed (T1-low / T2) locator fixes; AUTO_APPLY is default.
        if rec.get("action") in ("AUTO_APPLY", "REVIEW") and rec.get("proposed_fix"):
            pf = rec["proposed_fix"]
            rec["_manifest_item"] = {
                "yaml_path": fc["yaml_path"], "case_id": fc["case_id"],
                "step_key": pf["step_key"], "new_value": pf["new_value"],
                "repair_tier": rec["repair_tier"], "confidence": rec.get("confidence"),
            }
        return rec

    # no L1 diff -> escalate; assertion/flow regressions go to L4 (AI) if budget
    rec["root_cause"] = diff.get("reason", hint)
    if sig == "assertion" or tier in ("T3", "UNKNOWN"):
        if budget["used"] < budget["limit"]:
            budget["used"] += 1
            ctx = {
                "case_id": case_id, "yaml_path": yaml_path,
                "failed_step_key": fc["failed_step_key"], "step_index": step_idx,
                "err_msg": fc["err_msg"], "failure_signature": sig,
                "dom_context": dom_ctx,
                "candidate_locators": dom_ctx.get("candidate_locators", []),
                "original_locator": probe.get("original_locator"),
                "requirement_text": fetch_requirement(_ticket_from_case(fc)),
            }
            ai = heal_ai(ctx)
            rec["ai"] = ai
            rec["root_cause"] = ai.get("root_cause_hypothesis", rec["root_cause"])
            rec["action"] = "ESCALATE_AI" if ai.get("needs_human_review") else "REVIEW"
        else:
            rec["action"] = "DEFERRED_NEXT_RUN"
            rec["root_cause"] = (rec["root_cause"] + " | AI budget exhausted; deferred to next run.")
    else:
        rec["action"] = "REVIEW"
    return rec


def _ticket_from_case(fc: dict) -> str | None:
    """Best-effort Jira ticket extraction. Override per-run via HEAL_TICKET env."""
    return os.environ.get("HEAL_TICKET")


def write_reports(results: list, out_dir: str, manifest_items: list):
    os.makedirs(out_dir, exist_ok=True)
    json.dump({"results": results}, open(os.path.join(out_dir, "heal_report.json"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    manifest = {"manifest": manifest_items}
    json.dump(manifest, open(os.path.join(out_dir, "heal_manifest.json"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    lines = ["# Self-Heal Report", ""]
    counts = {}
    for r in results:
        counts[r["action"]] = counts.get(r["action"], 0) + 1
    lines.append("## Summary")
    for k, v in sorted(counts.items()):
        lines.append(f"- {k}: {v}")
    lines.append("")
    for r in results:
        lines.append(f"### {r['case_id']} [{r.get('status')}]  sig={r.get('failure_signature')}  tier={r.get('repair_tier')}")
        lines.append(f"- Failed step: `{r.get('failed_step_key')}` (idx {r.get('step_index')})")
        lines.append(f"- YAML: {r.get('yaml_path')}")
        lines.append(f"- Error: {str(r.get('err_msg',''))[:200]}")
        lines.append(f"- Root cause: {r.get('root_cause','')}")
        fix = r.get("proposed_fix")
        if fix:
            lines.append(f"- Proposed fix: `{fix.get('step_key')}` -> {json.dumps(fix.get('new_value'), ensure_ascii=False)}")
        lines.append(f"- Confidence: {r.get('confidence', 'n/a')}")
        lines.append(f"- **Action: {r['action']}**")
        lines.append("")
    open(os.path.join(out_dir, "heal_report.md"), "w", encoding="utf-8").write("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description="Self-heal orchestrator")
    ap.add_argument("--run", help="allure-results/<timestamp> dir (default: newest)")
    ap.add_argument("--limit", type=int, help="process only first N failures (testing)")
    ap.add_argument("--case", help="process only this case_id")
    ap.add_argument("--out", default=os.path.join(HEAL_DIR, "report"), help="report output dir")
    ap.add_argument("--apply", action="store_true", help="apply heal_manifest.json (one-click)")
    ap.add_argument("--include-t2", action="store_true", help="also apply T2 diffs")
    ap.add_argument("--no-ai", action="store_true", help="skip L4 AI (deterministic only)")
    ap.add_argument("--fast", action="store_true",
                    help="instant triage, NO browser (classify by error signature only)")
    ap.add_argument("--heavy", action="store_true",
                    help="acknowledge running the full browser probe on a large batch")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    manifest_path = os.path.join(args.out, "heal_manifest.json")
    if args.apply:
        manifest = json.load(open(manifest_path, encoding="utf-8")).get("manifest", [])
        applied, skipped = apply_manifest(manifest, include_t2=args.include_t2, dry_run=args.dry_run)
        print(f"Applied: {len(applied)}  Skipped: {len(skipped)}")
        for a in applied:
            print(f"  + {a['case_id']}.{a['step_key']}")
        return

    _, failures = parse_run(args.run)
    if args.case:
        failures = [f for f in failures if f["case_id"] == args.case]
    if args.limit:
        failures = failures[:args.limit]

    # Guard: a large browser-probe run will pin the machine for many minutes.
    # Force intentionality — triage with --fast first, or run heavy in a standalone terminal.
    if not args.fast and len(failures) > HEAVY_WARN_THRESHOLD and not args.heavy:
        print(f"WARNING: {len(failures)} failed cases need a browser probe each "
              f"(est. {len(failures) * 1.5:.0f}+ min) — this will slow your machine.")
        print("  Option A (instant):  python self_heal.py --run <ts> --fast --out <dir>")
        print("  Option B (heavy):    run in a STANDALONE terminal so the agent UI stays responsive:")
        print(f'    D:/Program Files/python.exe test_case/UI/Test_Katana/heal/self_heal.py '
              f'--run {args.run} --out {args.out} --heavy')
        print("  Progress is streamed to: " + os.path.join(args.out, "heal_progress.log"))
        return

    budget = {"used": 0, "limit": 0 if args.no_ai else AI_BUDGET}
    results = []
    manifest_items = []
    # truncate progress log for this run
    open(os.path.join(args.out, "heal_progress.log"), "w", encoding="utf-8").close()
    for fc in failures:
        print(f"[self_heal] {fc['case_id']} ...", flush=True)
        rec = process_case(fc, budget, fast=args.fast)
        results.append(rec)
        _write_progress(args.out, rec)
        if rec.get("_manifest_item"):
            manifest_items.append(rec["_manifest_item"])
        if rec.get("action") == "AUTO_APPLY" and rec.get("proposed_fix"):
            pf = rec["proposed_fix"]
            manifest_items.append({
                "yaml_path": fc["yaml_path"], "case_id": fc["case_id"],
                "step_key": pf["step_key"], "new_value": pf["new_value"],
                "repair_tier": rec["repair_tier"], "confidence": rec.get("confidence"),
            })

    write_reports(results, args.out, manifest_items)
    n_auto = sum(1 for r in results if r["action"] == "AUTO_APPLY")
    n_review = sum(1 for r in results if r["action"] in ("REVIEW", "ESCALATE_AI"))
    n_flaky = sum(1 for r in results if r["action"] == "FLAKY_CANDIDATE")
    n_def = sum(1 for r in results if r["action"] == "DEFERRED_NEXT_RUN")
    print(f"\nDone. AUTO_APPLY={n_auto}  REVIEW/ESCALATE={n_review}  "
          f"FLAKY={n_flaky}  DEFERRED={n_def}")
    print(f"Report: {os.path.join(args.out, 'heal_report.md')}")
    print(f"Manifest (one-click): {manifest_path}")


if __name__ == "__main__":
    main()
