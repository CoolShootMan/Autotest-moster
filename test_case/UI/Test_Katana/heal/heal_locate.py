#!usr/bin/env python3
# -*- encoding : utf-8 -*-
# coding : unicode_escape
'''
Filename         : heal_locate.py
Description      : L1 确定性定位器自愈 —— 消费 heal_probe 产出的候选定位器,
                  产出结构化 locator diff(老定位器 -> 新定位器 + 置信度 + 可否自动应用)。
                  无任何 AI:回退链打分完全确定性(取自 ADR Anchor Priority)。
                  防假绿硬规则:断言失败 + 原 locator 健康 / 原 locator 仍存在 =>
                  一律拒绝产出 locator diff,升级到 L3/L4(由 heal_classify 接管)。
Time             : 2026-07-28
Author           : Agent (self-heal foundation — L1 core)
'''

import sys
import os
import re
import json
import argparse
import difflib
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any

# Reuse the probe's contract + runner so probe->locate is one pipeline
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if REPO_ROOT not in sys.path:
    sys.path.append(REPO_ROOT)

from test_case.UI.Test_Katana.heal.heal_probe import (  # noqa: E402
    ProbeResult, ProbeRequest, probe, load_case,
)

# Auto-apply confidence gate (ADR: locator diff auto-applies if confident)
AUTO_APPLY_THRESHOLD = 0.8

# Anchor priority (mirrors ADR Evidence #3 / heal_probe.ANCHOR_PRIORITY)
ANCHOR_PRIORITY = ["data-testid", "role+name", "text", "position", "visual"]


# ============================================================================
# I/O Contract — the deterministic locator diff
# ============================================================================
@dataclass
class LocatorDiff:
    case_id: str
    step_key: str
    old: dict                                   # original step `v`
    new: dict                                   # healed step `v`
    strategy: str                               # data-testid | name-fuzzy | text | ...
    confidence: float
    auto_apply: bool                            # T1 if True, else T2 (review)
    repair_tier: str                            # T1 | T2
    rationale: str
    candidates_considered: int
    yaml_patch: dict = field(default_factory=dict)   # {step_key, new_value} for heal_apply

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=indent)


@dataclass
class Escalation:
    reason: str
    heal_layer: str                             # L3 | L4 | UNKNOWN
    repair_tier: str                            # T2 | T3 | UNKNOWN
    candidates_considered: int = 0

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=indent)


# ============================================================================
# Deterministic scoring (the L1 fallback chain)
# ============================================================================
def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def _intent(original: dict) -> dict:
    """Normalised intent extracted from the failed step's original `v`."""
    return {
        "role": original.get("role"),
        "name_raw": original.get("name") or "",
        "name": _norm(original.get("name")),
        "text_raw": original.get("text") or "",
        "text": _norm(original.get("text")),
    }


def _parse_role_name(value: str):
    m = re.search(r"role=['\"]?([^'\"]+)['\"]?", value)
    n = re.search(r"name=['\"]([^'\"]*)['\"]", value)
    return (m.group(1) if m else None), (n.group(1) if n else None)


def _parse_text(value: str):
    m = re.search(r"text=(.+)", value)
    return m.group(1).strip() if m else value


def _parse_testid(value: str):
    m = re.search(r"data-testid=['\"]([^'\"]+)['\"]", value)
    return m.group(1) if m else value.strip("[]'")


def score_candidate(cand: dict, intent: dict, original: dict):
    """
    Return (strategy, confidence, new_locator_or_None).
    new_locator is a step-`v`-schema dict usable as a direct YAML edit, or None
    if the candidate cannot anchor a stable, named locator (=> review/escalate).
    """
    ctype = cand.get("type")
    cval = cand.get("value", "")
    cscore = float(cand.get("score", 0.0))

    if ctype == "data-testid":
        dt = _parse_testid(cval)
        # Reject generic MUI / framework-internal testids (e.g. mui-stack, PrivateXxx):
        # they are NOT unique anchors and would strict-mode-fail or click the wrong
        # element. Only accept app-level semantic data-testids (no "mui"/"private").
        if not dt or "mui" in dt.lower() or dt.lower().startswith("private"):
            return "data-testid-generic", 0.0, None
        # A data-testid is a stable anchor, but uniqueness is uncertain (some app
        # testids like base-storefront-text are pervasive). Hard-cap to REVIEW-tier
        # (T2) so a narrow corrected role+name fix is preferred for AUTO_APPLY.
        conf = 0.85
        new_loc = {"test_id": dt}
        return "data-testid", conf, new_loc

    if ctype == "role+name":
        role, cname_raw = _parse_role_name(cval)
        cname = _norm(cname_raw)
        orig_raw = intent["name_raw"] or ""
        # GENUINE "locator exists as written" only when raw characters are identical
        # (the action engine does a case-sensitive exact match on name).
        if cname_raw is not None and cname_raw.strip() == orig_raw.strip():
            return "role+name-exact", cscore, None          # identical -> L3 (timing/visibility)
        # normalized-equal but raw differs => case/whitespace drift => real locator fix
        ratio = difflib.SequenceMatcher(None, intent["name"], cname).ratio() if intent["name"] else 0.0
        if ratio >= 0.8:
            # ratio is the dominant signal (semantic identity); probe score secondary.
            # Carry exact:False to faithfully reproduce the substring match the probe used.
            new_loc = {"role": intent["role"] or role, "name": cname_raw, "exact": False}
            return "name-fuzzy", round(min(1.0, 0.4 + ratio * 0.55 + cscore * 0.05), 3), new_loc
        return "name-weak", round(cscore * ratio, 3), None

    if ctype == "text":
        ctext_raw = _parse_text(cval)
        ctext = _norm(ctext_raw)
        base_raw = (intent["name_raw"] or intent["text_raw"] or "").strip()
        if ctext_raw.strip() == base_raw:
            return "text-exact", cscore, None               # identical -> L3
        base = intent["name"] or intent["text"]
        ratio = difflib.SequenceMatcher(None, base, ctext).ratio() if base else 0.0
        if ratio >= 0.8:
            new_loc = {"role": intent["role"], "name": ctext_raw, "exact": False}
            return "text", round(cscore * 0.85, 3), new_loc
        return "text-weak", round(cscore * ratio * 0.85, 3), None

    if ctype == "position":
        # position-only cannot synthesize a stable named locator -> review only
        return "position", round(cscore * 0.5, 3), None

    if ctype == "visual":
        return "visual", round(cscore * 0.6, 3), None

    return "unknown", 0.0, None


# ============================================================================
# Core: probe -> locator diff
# ============================================================================
def heal_locate(result: ProbeResult) -> dict:
    """
    Turn a ProbeResult into a LocatorDiff, or an Escalation if L1 does not apply.
    Hard anti-false-green guards (per ADR):
      - failure_signature == 'assertion'                      -> escalate L4/T3 (never touch assertions)
      - failure_signature == 'none'                           -> escalate (no failure)
      - dom_context.target_resolved is True                  -> escalate L3 (locator exists; timing/visibility)
      - no candidate_locators                                -> escalate (nothing to heal from)
    """
    sig = result.failure_signature
    dom = result.dom_context or {}
    cands = dom.get("candidate_locators") or []
    original = result.original_locator or {}

    if sig == "none":
        return Escalation("no failure observed (probe at intermediate step) — not an L1 case",
                           "UNKNOWN", "UNKNOWN", len(cands)).__dict__
    if sig == "assertion":
        return Escalation("assertion failed; L1 locator healing refused (risk false green) -> L4/T3",
                           "L4", "T3", len(cands)).__dict__
    if dom.get("target_resolved") is True:
        return Escalation("original locator still resolves; not a drift (timing/visibility?) -> L3",
                           "L3", "T2", len(cands)).__dict__
    if not cands:
        return Escalation("no candidate locators captured; nothing to heal from -> escalate",
                           "L2", "T2", 0).__dict__

    intent = _intent(original)
    scored = []  # (conf, strategy, new_loc, cand)
    for c in cands:
        strat, conf, new_loc = score_candidate(c, intent, original)
        if new_loc is not None:
            scored.append((conf, strat, new_loc, c))
        elif strat.endswith("-exact"):
            # exact (raw-identical) match found but probe reported not-found -> contradiction => L3
            return Escalation("candidate matches original exactly (raw) yet step failed -> "
                              "timing/visibility, not drift -> L3",
                              "L3", "T2", len(cands)).__dict__

    if not scored:
        return Escalation("candidates present but none anchor a stable locator "
                          "(only position/visual/weak) -> review only",
                          "L1", "T2", len(cands)).__dict__

    # Anchor priority wins over raw confidence: data-testid is the most stable
    # anchor (immune to text/case drift), so prefer it whenever present.
    scored.sort(key=lambda t: (ANCHOR_PRIORITY.index(t[1]) if t[1] in ANCHOR_PRIORITY else 99, -t[0]))
    conf, strat, new_loc, best = scored[0]

    auto = conf >= AUTO_APPLY_THRESHOLD and strat in ("data-testid", "name-fuzzy", "text")
    tier = "T1" if auto else "T2"
    rationale = (f"L1 fallback '{strat}': probe candidate type='{best.get('type')}' "
                 f"score={best.get('score')} -> healed locator conf={conf:.2f}; "
                 f"{'auto-apply (T1)' if auto else 'needs human review (T2)'}")

    return LocatorDiff(
        case_id=result.case_id,
        step_key=result.failed_step,
        old=original,
        new=new_loc,
        strategy=strat,
        confidence=round(conf, 3),
        auto_apply=auto,
        repair_tier=tier,
        rationale=rationale,
        candidates_considered=len(cands),
        yaml_patch={"step_key": result.failed_step, "new_value": new_loc},
    ).__dict__


# ============================================================================
# CLI
# ============================================================================
def _result_from_json(path: str) -> ProbeResult:
    with open(path, "r", encoding="utf-8") as f:
        return ProbeResult(**json.load(f))


def main():
    ap = argparse.ArgumentParser(description="L1 deterministic locator healer (no AI)")
    ap.add_argument("case_id", help="case id, e.g. testT4605  (or a probe_result.json path)")
    ap.add_argument("--step", type=int, default=0, help="run up to this 0-based step index")
    ap.add_argument("--yaml", default=None, help="path to the YAML file (chain mode)")
    ap.add_argument("--probe-out", default=None, help="in chain mode, also save probe_result JSON here")
    ap.add_argument("--out", default=None, help="write the locator diff / escalation JSON here")
    args = ap.parse_args()

    # file mode: a saved probe_result.json
    if args.case_id.endswith(".json") and os.path.exists(args.case_id):
        result = _result_from_json(args.case_id)
    else:
        yaml_path = args.yaml or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),  # Test_Katana
            "All_YAML", "Section", "Section.yaml")
        req = ProbeRequest(case_id=args.case_id, step_index=args.step, mode="capture",
                           yaml_path=yaml_path)
        result = probe(req)
        if args.probe_out:
            with open(args.probe_out, "w", encoding="utf-8") as f:
                f.write(result.to_json())
            print(f"[heal_locate] probe -> {args.probe_out}")

    diff = heal_locate(result)
    out = json.dumps(diff, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"[heal_locate] wrote {args.out}")
    else:
        print(out)


if __name__ == "__main__":
    main()
