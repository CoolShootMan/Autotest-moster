"""
heal_classify.py — Deterministic routing for the self-healing pipeline.

The authoritative failure classifier lives in heal_probe.classify (signature /
heal-layer / repair-tier / hint). This module wraps it with routing decisions
and a corpus backfill helper so the triage logic is also validated by the
ground-truth corpus.

Routing rules (deterministic, no AI):
  - T1 + confidence >= AUTO_CONF  -> AUTO_APPLY   (locator drift, safe)
  - T2                            -> REVIEW        (need human/AI confirmation)
  - T3 / UNKNOWN                  -> ESCALATE      (flow/requirement regression;
                                                     never auto-fix, may go to L4 AI)
"""
from __future__ import annotations

import sys
import os
import json

HERE = os.path.abspath(__file__)
REPO_ROOT = HERE
while not os.path.exists(os.path.join(REPO_ROOT, 'pytest.ini')) and REPO_ROOT != os.path.dirname(REPO_ROOT):
    REPO_ROOT = os.path.dirname(REPO_ROOT)
if REPO_ROOT not in sys.path:
    sys.path.append(REPO_ROOT)

from test_case.UI.Test_Katana.heal.heal_probe import classify  # noqa: E402

AUTO_CONF = 0.9  # confidence at/above which a T1 locator diff is auto-applied


def route(signature: str, tier: str, confidence: float = 1.0, strategy: str = "") -> str:
    """Return AUTO_APPLY | REVIEW | ESCALATE."""
    if tier == "T1" and confidence >= AUTO_CONF:
        return "AUTO_APPLY"
    if tier in ("T1", "T2"):
        # T1 below auto-confidence, or any T2 -> human review (apply with --include-t2)
        return "REVIEW"
    return "ESCALATE"


def classify_failure(err_msg: str, dom_ctx: dict | None = None):
    """Thin wrapper over heal_probe.classify for orchestrator use."""
    return classify(err_msg, dom_ctx or {})


def backfill_corpus_tier(corpus_path: str) -> int:
    """Add a derived `repair_tier` field to every heal_corpus.json entry.

    Mapping (from ADR triage):
      L1 locator-drift         -> T1 (auto when confident)
      L1-internal assertion-bug -> T1 (heal-the-healer, auto)
      L2 precondition/selector  -> T2 (review)
      L4 stale-flow-logic       -> T3 (escalate, needs requirement context)
      L0 stale-label            -> T1 (auto label wipe, zero cost)
    Returns number of entries updated.
    """
    if not os.path.exists(corpus_path):
        print(f"corpus not found: {corpus_path}")
        return 0
    data = json.load(open(corpus_path, encoding="utf-8"))
    tier_map = {
        "L1": "T1",
        "L1-internal": "T1",
        "L2": "T2",
        "L4": "T3",
        "L0": "T1",
    }
    updated = 0
    for entry in data.get("entries", []):
        layer = entry.get("heal_layer") or entry.get("layer")
        if layer in tier_map and "repair_tier" not in entry:
            entry["repair_tier"] = tier_map[layer]
            updated += 1
    if updated:
        json.dump(data, open(corpus_path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        print(f"backfilled repair_tier on {updated} entries in {corpus_path}")
    else:
        print("no entries needed backfill (all already have repair_tier)")
    return updated


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=os.path.join(os.path.dirname(__file__), "..", "..", "..", "..",
                                                       ".workbuddy", "self-healing", "heal_corpus.json"))
    args = ap.parse_args()
    backfill_corpus_tier(os.path.abspath(args.corpus))
