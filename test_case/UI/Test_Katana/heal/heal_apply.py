"""
heal_apply.py — Apply healing diffs to YAML test cases.

Consumes the `yaml_patch` produced by heal_locate (or a manifest of patches)
and writes the fix back to the case YAML. Safety:
  - Always writes a single .heal_bak backup before mutating.
  - T1 diffs auto-apply; T2/T3 require explicit --include-t2 (human gate).
  - dry_run prints the before/after without touching disk.
"""
from __future__ import annotations

import sys
import os
import yaml
import shutil

HERE = os.path.abspath(__file__)
REPO_ROOT = HERE
while not os.path.exists(os.path.join(REPO_ROOT, 'pytest.ini')) and REPO_ROOT != os.path.dirname(REPO_ROOT):
    REPO_ROOT = os.path.dirname(REPO_ROOT)
if REPO_ROOT not in sys.path:
    sys.path.append(REPO_ROOT)


def apply_diff(yaml_path: str, case_id: str, step_key: str, new_value: dict,
               backup: bool = True, dry_run: bool = False):
    """Replace case[test_step][step_key] with new_value. Returns (ok, info)."""
    if not os.path.exists(yaml_path):
        return False, f"no such file: {yaml_path}"
    if backup and not dry_run:
        shutil.copy(yaml_path, yaml_path + ".heal_bak")
    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    case = data.get(case_id)
    if not case:
        return False, f"case '{case_id}' not found in {yaml_path}"
    ts = case.setdefault("test_step", {})
    if step_key not in ts:
        return False, f"step '{step_key}' not found in case '{case_id}'"
    old = ts[step_key]
    if dry_run:
        return True, {"old": old, "new": new_value, "dry_run": True}
    ts[step_key] = new_value
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    return True, {"old": old, "new": new_value}


def apply_manifest(manifest: list, include_t2: bool = False, dry_run: bool = False):
    """Apply a list of patch dicts: {yaml_path, case_id, step_key, new_value, repair_tier}.

    Returns (applied, skipped).
    """
    applied, skipped = [], []
    for item in manifest:
        tier = item.get("repair_tier")
        if tier == "T1" or (include_t2 and tier == "T2"):
            ok, info = apply_diff(
                item["yaml_path"], item["case_id"], item["step_key"],
                item["new_value"], dry_run=dry_run)
            (applied if ok else skipped).append({**item, "info": info})
        else:
            skipped.append({**item, "info": "gated (tier not auto-applied)"})
    return applied, skipped


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Apply a heal_manifest.json.")
    ap.add_argument("--manifest", required=True, help="heal_manifest.json path")
    ap.add_argument("--include-t2", action="store_true", help="also apply T2 (human-confirmed) diffs")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    manifest = json.load(open(args.manifest, encoding="utf-8")).get("manifest", [])
    applied, skipped = apply_manifest(manifest, include_t2=args.include_t2, dry_run=args.dry_run)
    print(f"Applied: {len(applied)}  Skipped: {len(skipped)}")
    for a in applied:
        print(f"  + {a['case_id']}.{a['step_key']} -> {a['new_value']}")
    for s in skipped:
        print(f"  - {s['case_id']}.{s.get('step_key')} ({s.get('repair_tier')}): {s.get('info')}")
