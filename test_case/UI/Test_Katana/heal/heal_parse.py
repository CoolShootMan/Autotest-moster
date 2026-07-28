"""
heal_parse.py — Report ingestion for the self-healing pipeline.

Reads an Allure results run (allure-results/<timestamp>/) and extracts every
failed/broken test case into a structured FailedCase record that downstream
tools (heal_probe / heal_locate / heal_classify / heal_apply) can consume.

Key facts learned from the real report schema (allure 2.x result.json):
  - case_id          = result['name']                 (e.g. 'testT2705_VerifyGuest')
  - yaml relative    = labels subSuite = 'test_case[All_YAML/Post/Post_setting.yaml'
                       -> strip brackets -> 'All_YAML/Post/Post_setting.yaml'
  - failure message  = result['statusDetails']['message']
                       e.g. "Exception: smart_click: element not found: Image of Product"
  - full traceback   = result['statusDetails']['trace']  (contains original locator dict v = {...})
  - The action engine logs the whole test_step as ONE coarse allure step, so the
    precise YAML sub-step must be re-derived by matching the failure target
    (name/locator) against the case's test_step dict.

No browser needed — pure offline report parsing.
"""
from __future__ import annotations

import sys
import os
import re
import json
import glob
import ast

# Make repo root importable so we can reuse heal_probe.load_case / classify
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if REPO_ROOT not in sys.path:
    sys.path.append(REPO_ROOT)

from test_case.UI.Test_Katana.heal.heal_probe import load_case, classify  # noqa: E402

KATANA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../Test_Katana


def newest_run() -> str | None:
    base = "allure-results"
    if not os.path.isdir(base):
        return None
    dirs = [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))]
    return os.path.join(base, sorted(dirs)[-1]) if dirs else None


def extract_target(err_msg: str, trace: str) -> str | None:
    """Best-effort extraction of the failed element target name/locator."""
    # 1. smart_click: element not found: <NAME or full xpath>  (capture to end of line)
    m = re.search(r"element not found:\s*(.+)", err_msg or "", re.S)
    if m:
        return m.group(1).strip().strip("'\"")
    # 2. name='X' in message
    m = re.search(r"name='([^']+)'", err_msg or "")
    if m:
        return m.group(1)
    # 3. original locator dict v = {...} inside the traceback
    m = re.search(r"v = (\{.*?\})", trace or "", re.S)
    if m:
        try:
            d = ast.literal_eval(m.group(1))
            for fld in ("name", "text", "value"):
                if isinstance(d.get(fld), str):
                    return d[fld]
            if isinstance(d.get("locator"), str):
                return d["locator"]
        except Exception:
            pass
    return None


def locate_failed_step(yaml_path: str, case_id: str, err_msg: str, trace: str):
    """Return (failed_step_key, 1-based step_index) by matching target against test_step.

    Two-pass: exact field equality first, then substring containment (covers
    xpath locators where the failure message carries the full xpath string).
    """
    try:
        case = load_case(yaml_path, case_id)
    except Exception:
        return "", 0
    steps = case.get("test_step") or {}
    target = extract_target(err_msg, trace)
    if target:
        t = target.lower()
        # pass 1: exact match on name/text/value/locator
        for i, (k, v) in enumerate(steps.items(), start=1):
            if isinstance(v, dict):
                for fld in ("name", "text", "value", "locator"):
                    val = v.get(fld)
                    if isinstance(val, str) and val.lower() == t:
                        return k, i
        # pass 2: substring containment (xpath / locator drift)
        for i, (k, v) in enumerate(steps.items(), start=1):
            if isinstance(v, dict):
                hay = " ".join(str(x) for x in v.values() if isinstance(x, str)).lower()
                if t and t in hay:
                    return k, i
    keys = list(steps.keys())
    return (keys[-1] if keys else ""), len(keys)


def yaml_path_from_labels(labels: list) -> str:
    for lab in labels or []:
        if lab.get("name") == "subSuite":
            # format: 'test_case[All_YAML/Post/Post_setting.yaml' (opening '[' only, no close)
            mm = re.search(r"\[(.*)$", lab.get("value", ""))
            if mm:
                return os.path.join(KATANA_DIR, mm.group(1))
    return ""


def parse_run(run_dir: str | None = None):
    """Parse a run dir. Returns (run_dir, [FailedCase dicts])."""
    run_dir = run_dir or newest_run()
    if not run_dir or not os.path.isdir(run_dir):
        raise SystemExit(f"no allure run dir found: {run_dir}")
    out = []
    for f in sorted(glob.glob(os.path.join(run_dir, "*-result.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        st = d.get("status")
        if st not in ("failed", "broken"):
            continue
        name = d.get("name", "")
        yaml_path = yaml_path_from_labels(d.get("labels", []))
        sd = d.get("statusDetails") or {}
        err_msg = sd.get("message", "")
        trace = sd.get("trace", "")
        step_key, step_index = locate_failed_step(yaml_path, name, err_msg, trace)
        sig, layer, tier, hint = classify(err_msg, {})  # no DOM yet -> conservative T2 pre-class
        out.append({
            "case_id": name,
            "yaml_path": yaml_path,
            "status": st,
            "err_msg": err_msg,
            "trace": trace,
            "failed_step_key": step_key,
            "step_index": step_index,
            "failure_signature": sig,
            "heal_layer_suggestion": layer,
            "repair_tier": tier,
            "root_cause_hint": hint,
        })
    return run_dir, out


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Parse an Allure run into failed cases.")
    ap.add_argument("--run", help="allure-results/<timestamp> dir (default: newest)")
    ap.add_argument("--json", help="write failures to this JSON path")
    ap.add_argument("--case", help="filter to a single case_id")
    args = ap.parse_args()

    run_dir, failures = parse_run(args.run)
    if args.case:
        failures = [f for f in failures if f["case_id"] == args.case]
    print(f"Run: {run_dir}")
    print(f"Failed/Broken cases: {len(failures)}\n")
    for f in failures:
        print(f"  {f['case_id']}  [{f['status']}]  sig={f['failure_signature']} "
              f"tier={f['repair_tier']}")
        print(f"    yaml : {f['yaml_path']}")
        print(f"    step : {f['failed_step_key']} (idx {f['step_index']})")
        print(f"    err  : {f['err_msg'][:110]}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"run_dir": run_dir, "failures": failures}, fh, indent=2, ensure_ascii=False)
        print(f"\nWrote {args.json}")


if __name__ == "__main__":
    main()
