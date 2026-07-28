#!usr/bin/env python3
# -*- encoding : utf-8 -*-
# coding : unicode_escape
'''
Filename         : heal_probe.py
Description      : 自愈诊断探针工具(确定性,无 AI)。
                  替代手工 tmp_probe_*.py:受控重跑到失败步,抓取 DOM 上下文 +
                  候选定位器 + 前置状态 + 与基线相似度,并可跑结构化假设实验。
                  输出结构化 probe_result JSON,同时喂 L1/L2/L4 并反哺语料。
                  (ADR-001 「Diagnostic Probe Tool」段; 复用现有 action engine)
Time             : 2026-07-28
Author           : Agent (self-heal foundation)
'''

import sys
import os
import json
import argparse
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any

import yaml
from playwright.sync_api import sync_playwright, Page, Browser

# --- Add repo root to sys.path so we can reuse the case action engine ---
# heal_probe.py lives at <repo>/test_case/UI/Test_Katana/heal/heal_probe.py
#   parents[0]=heal  [1]=Test_Katana  [2]=UI  [3]=test_case  [4]=repo-root
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if REPO_ROOT not in sys.path:
    sys.path.append(REPO_ROOT)

from test_case.UI.Test_Katana.actions import get_action, create_session  # noqa: E402

# Auth storage_state used by the cases (same as conftest page fixture)
COOKIE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),  # Test_Katana
    "cookie_release.json",
)
BASE_URL = os.environ.get("BASE_URL", "https://release.pear.us")
KATANA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../Test_Katana (heal/..)
DEFAULT_YAML = os.path.join(KATANA_DIR, "All_YAML", "Section", "Section.yaml")


# ============================================================================
# I/O Contract (mirrors ADR-001 probe_result schema)
# ============================================================================
@dataclass
class CandidateLocator:
    type: str          # data-testid | role+name | text | position
    value: str
    score: float       # 0..1 deterministic confidence


@dataclass
class ProbeRequest:
    case_id: str
    step_index: int
    mode: str = "capture"                    # capture | hypothesis | diff
    yaml_path: str = DEFAULT_YAML
    hypothesis: Optional[dict] = None        # mode=hypothesis: {alt_action, alt_value}
    baseline_fingerprint: Optional[dict] = None  # mode=diff: author-period fingerprint


@dataclass
class ProbeResult:
    case_id: str
    failed_step: str
    failure_signature: str                   # not-found | timeout | assertion | exception | none
    original_locator: dict = field(default_factory=dict)   # the failed step's original `v` dict (diff base)
    dom_context: dict = field(default_factory=dict)        # target_selector, subtree_html, candidate_locators
    precondition_state: dict = field(default_factory=dict)
    similarity_to_baseline: Optional[float] = None
    hypothesis_tests: list = field(default_factory=list)
    observed_root_cause_hint: str = ""
    heal_layer_suggestion: str = "UNKNOWN"   # L1 | L2 | L3 | L4 | UNKNOWN
    repair_tier: str = "UNKNOWN"             # T1 | T2 | T3 | UNKNOWN
    notes: str = ""

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=indent)


# Stable-anchor priority (from ADR Evidence #3) used to rank candidate locators
ANCHOR_PRIORITY = ["data-testid", "role+name", "text", "position"]


# ============================================================================
# Case loading (reuses the same YAML the runner consumes)
# ============================================================================
# Mirror conftest._replace_placeholders / _resolve_base_url exactly so the probe
# and the pytest runner see identical step values ({BASE_URL} / {ENV} expansion).
_ENV_MAP = {
    "https://staging.pear.us": "staging",
    "https://release.pear.us": "release",
    "https://pear.us": "prod",
}


def _replace_placeholders(obj, base_url, env_name):
    """Recursively replace {BASE_URL} and {ENV} placeholders (same as conftest)."""
    if isinstance(obj, str):
        return obj.replace("{BASE_URL}", base_url).replace("{ENV}", env_name)
    elif isinstance(obj, dict):
        return {k: _replace_placeholders(v, base_url, env_name) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_replace_placeholders(item, base_url, env_name) for item in obj]
    return obj


def load_case(yaml_path: str, case_id: str) -> dict:
    """Load a single case dict by id from a YAML file, expanding {BASE_URL}/{ENV}
    placeholders exactly like the pytest runner does at collection time."""
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    base_url = os.environ.get("BASE_URL", "https://release.pear.us")
    env_name = _ENV_MAP.get(base_url, "release")
    if data:
        data = _replace_placeholders(data, base_url, env_name)
    if case_id not in data:
        raise KeyError(f"case '{case_id}' not found in {yaml_path}")
    case = dict(data[case_id])
    case["__yaml_path__"] = yaml_path
    case["__case_id__"] = case_id
    return case


def steps_list(case: dict) -> List[tuple]:
    """Ordered (key, value) list of test_step entries."""
    return list(case.get("test_step", {}).items())


def step_target_hint(step_value: Any) -> dict:
    """Extract a locator hint from a step's value dict for DOM capture."""
    if not isinstance(step_value, dict):
        return {}
    hint = {}
    if "locator" in step_value:
        hint["locator"] = step_value["locator"]
    if "role" in step_value:
        hint["role"] = step_value["role"]
    if "name" in step_value:
        hint["name"] = step_value["name"]
    if "text" in step_value:
        hint["text"] = step_value["text"]
    if "index" in step_value:
        hint["index"] = step_value["index"]
    return hint


# ============================================================================
# Browser session (mirrors conftest page fixture auth)
# ============================================================================
def create_page(headless: bool = True) -> tuple:
    """Launch chromium with the case auth storage_state. Returns (playwright, browser, page)."""
    if not os.path.exists(COOKIE_PATH):
        raise FileNotFoundError(f"auth cookie not found: {COOKIE_PATH}")
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=headless)
    context = browser.new_context(storage_state=COOKIE_PATH)
    page = context.new_page()
    page.set_default_timeout(30000)
    return pw, browser, page


# ============================================================================
# Execution (reuses get_action — the SAME engine as test_ui.py)
# ============================================================================
def run_to_step(case: dict, stop_index: int, page: Page):
    """
    Execute steps 0..stop_index (inclusive) via the action engine.
    Returns (executed_count, error, failed_step_key).
    If stop_index >= len(steps), runs all steps.
    """
    steps = steps_list(case)
    executed = 0
    error = None
    failed_key = None
    # Optional pre_condition
    pre = case.get("pre_condition", {})
    if pre:
        for pk, pv in pre.get("test_step", {}).items():
            act = get_action(pk)
            if act:
                try:
                    act(page, pv)
                except Exception as e:
                    # pre-conditions are non-blocking per runner
                    pass
    for i, (k, v) in enumerate(steps):
        if i > stop_index:
            break
        act = get_action(k)
        if not act:
            # legacy fallback (text click) — keep parity with runner
            if isinstance(v, dict) and v.get("text"):
                try:
                    page.click(f"text={v['text']}", timeout=5000)
                    executed += 1
                    continue
                except Exception:
                    pass
            error = f"step '{k}' not found in Action Registry"
            failed_key = k
            break
        try:
            act(page, v)
            executed += 1
        except Exception as e:
            error = str(e)
            failed_key = k
            break
    return executed, error, failed_key


def run_teardown(case: dict, page: Page):
    """Execute teardown_step actions so a probe never leaves test sections behind."""
    for k, v in case.get("teardown_step", {}).items():
        act = get_action(k)
        if act:
            try:
                act(page, v)
            except Exception:
                pass


# ============================================================================
# DOM capture (the deterministic diagnostic core)
# ============================================================================
def _rank_candidate_locators(element) -> List[CandidateLocator]:
    """Given a resolved element, produce ranked candidate locators by stable-anchor priority."""
    cands: List[CandidateLocator] = []
    try:
        dt = element.get_attribute("data-testid")
        if dt:
            cands.append(CandidateLocator("data-testid", f"[data-testid='{dt}']", 0.95))
    except Exception:
        pass
    try:
        role = element.get_attribute("role")
        name = element.get_attribute("name") or element.inner_text()[:40] if False else None
        # name attr may be absent; fall back to aria-label / text
        aria = element.get_attribute("aria-label")
        text = ""
        try:
            text = (element.inner_text() or "").strip()[:40]
        except Exception:
            pass
        if role and (aria or text):
            val = f"role={role} name='{aria or text}'"
            cands.append(CandidateLocator("role+name", val, 0.85))
    except Exception:
        pass
    try:
        text = (element.inner_text() or "").strip()[:40]
        if text:
            cands.append(CandidateLocator("text", f"text={text}", 0.6))
    except Exception:
        pass
    return cands


def capture_dom_context(page: Page, hint: dict) -> dict:
    """
    Best-effort DOM capture around the failure target.
    - If the target resolves: serialize its subtree + rank candidate locators.
    - If not found: page-wide search for partial matches (feeds L1 fallback).
    """
    ctx: dict = {"target_selector": None, "subtree_html": None, "candidate_locators": []}
    target = None
    # 1) try explicit locator
    if hint.get("locator"):
        try:
            el = page.locator(hint["locator"]).first
            if el.count() and el.is_visible(timeout=2000):
                target = el
                ctx["target_selector"] = hint["locator"]
        except Exception:
            pass
    # 2) try role+name
    if target is None and hint.get("role"):
        try:
            sel = f"[role='{hint['role']}']"
            if hint.get("name"):
                sel += f"#{ '' if False else '' }"
            el = page.get_by_role(hint["role"], name=hint.get("name")).first
            if el.count() and el.is_visible(timeout=2000):
                target = el
                ctx["target_selector"] = f"role={hint['role']} name='{hint.get('name')}'"
        except Exception:
            pass
    # 3) try text
    if target is None and hint.get("text"):
        try:
            el = page.get_by_text(hint["text"], exact=False).first
            if el.count() and el.is_visible(timeout=2000):
                target = el
                ctx["target_selector"] = f"text={hint['text']}"
        except Exception:
            pass

    if target is not None:
        try:
            ctx["subtree_html"] = target.evaluate("el => el.outerHTML").get("value", "")[:2000] \
                if False else target.evaluate("el => el.outerHTML")[:2000]
        except Exception:
            pass
        ctx["candidate_locators"] = [asdict(c) for c in _rank_candidate_locators(target)]
        ctx["target_resolved"] = True
    else:
        # Not found: search page-wide for partial matches to feed L1 fallback.
        # Capture BOTH role+name AND any data-testid anchor (the stable L1 target).
        ctx["target_resolved"] = False
        partials = []
        if hint.get("name"):
            try:
                # substring role+name (catches minor text drift that exact match misses)
                els = page.get_by_role(hint.get("role", "*"), name=hint.get("name"), exact=False).all()
                for el in els[:5]:
                    partials.append(asdict(CandidateLocator(
                        "role+name",
                        f"role={hint.get('role')} name='{hint.get('name')}'", 0.7)))
                    # also record the data-testid anchor if the element has one
                    try:
                        dt = el.get_attribute("data-testid")
                        if dt:
                            partials.append(asdict(CandidateLocator(
                                "data-testid", f"[data-testid='{dt}']", 0.9)))
                    except Exception:
                        pass
            except Exception:
                pass
            # image alt-text substring search (key for role=img targets like product cards)
            try:
                els = page.get_by_alt_text(hint["name"], exact=False).all()
                for el in els[:5]:
                    partials.append(asdict(CandidateLocator(
                        "role+name", f"role=img name='{hint['name']}'", 0.7)))
                    try:
                        dt = el.get_attribute("data-testid")
                        if dt:
                            partials.append(asdict(CandidateLocator(
                                "data-testid", f"[data-testid='{dt}']", 0.9)))
                    except Exception:
                        pass
            except Exception:
                pass
            # Text-based partial search (Playwright does case-insensitive substring match).
            # This catches case/whitespace drift that the exact role+name search misses.
            try:
                els = page.get_by_text(hint["name"], exact=False).all()
                for el in els[:5]:
                    try:
                        role = el.get_attribute("role") or hint.get("role")
                        aria = el.get_attribute("aria-label")
                        txt = (el.inner_text() or "").strip()
                        nm = aria or txt
                        partials.append(asdict(CandidateLocator(
                            "role+name", f"role={role} name='{nm}'", 0.8)))
                        dt = el.get_attribute("data-testid")
                        if dt:
                            partials.append(asdict(CandidateLocator(
                                "data-testid", f"[data-testid='{dt}']", 0.9)))
                    except Exception:
                        pass
            except Exception:
                pass
        ctx["candidate_locators"] = partials
    return ctx


def capture_precondition_state(page: Page) -> dict:
    """
    Domain-specific precondition snapshot for the storefront (extensible).
    These are exactly the N-2 state signals the ADR says L2 must record.
    """
    state: dict = {}
    try:
        # number of sections (header anchors)
        state["section_count"] = page.locator("p[data-testid='base-storefront-text']").count()
    except Exception:
        state["section_count"] = -1
    try:
        # "Your item is ready!" ready dialog open?
        state["ready_dialog_open"] = page.get_by_text("Your item is ready!", exact=False).first.is_visible(timeout=1500)
    except Exception:
        state["ready_dialog_open"] = False
    try:
        # any horizontal carousel scroller present?
        state["carousel_scroller_present"] = page.locator("div[style*='overflow-x: auto']").count() > 0
    except Exception:
        state["carousel_scroller_present"] = False
    return state


# ============================================================================
# Deterministic classification (the anti-false-green rule from ADR)
# ============================================================================
def classify(error: Optional[str], dom_ctx: dict) -> tuple:
    """
    Returns (failure_signature, heal_layer_suggestion, repair_tier, root_cause_hint).
    Hard rule: assertion-failed + target locators HEALTHY  => NOT locator drift,
    route to escalate (L4/UNKNOWN, T3) — never auto-fix. This prevents false green.
    """
    if error is None:
        return "none", "L0", "T1", "no failure observed (probe at intermediate step)"
    err = (error or "").lower()
    # Assertion failures take precedence: the test completed and the expected
    # condition was not met -> NEVER a locator-drift auto-fix case. Escalate.
    if "assertion" in err or "assert false" in err or "expected" in err or "should be" in err:
        if dom_ctx.get("target_resolved") is True:
            return ("assertion", "L4", "T3",
                    "assertion failed but target locators healthy -> NOT locator drift; "
                    "likely flow/requirement regression -> escalate (do NOT auto-fix)")
        return ("assertion", "L2", "T2", "assertion failed; inspect precondition state")
    if "not found" in err or "timeout" in err or "locator" in err:
        # target could not be resolved -> locator drift candidate
        if dom_ctx.get("target_resolved") is False and dom_ctx.get("candidate_locators"):
            return ("not-found", "L1", "T1",
                    "target locator missing but candidates present -> locator drift (L1 fallback)")
        return ("not-found", "L1", "T2", "target locator missing")
    if "exception" in err:
        return ("exception", "L3", "T2", "unexpected exception during step")
    return ("exception", "UNKNOWN", "UNKNOWN", "unclassified")


# ============================================================================
# Orchestrator
# ============================================================================
def probe(req: ProbeRequest) -> ProbeResult:
    case = load_case(req.yaml_path, req.case_id)
    steps = steps_list(case)
    # clamp stop_index
    stop = min(req.step_index, len(steps) - 1) if steps else 0

    pw, browser, page = None, None, None
    try:
        pw, browser, page = create_page()
        page.goto(BASE_URL, wait_until="domcontentloaded")
        executed, error, failed_key = run_to_step(case, stop, page)

        # capture the failed step's original `v` dict as the diff base for heal_locate
        from_step = case.get("test_step", {})
        orig = dict(from_step.get(failed_key, {}) or {}) if failed_key else {}

        hint = step_target_hint(steps[stop][1]) if stop < len(steps) else {}
        dom_ctx = capture_dom_context(page, hint)
        pre_state = capture_precondition_state(page)
        sig, layer, tier, hint_msg = classify(error, dom_ctx)

        # similarity to baseline (mode=diff) — placeholder until fingerprints land
        similarity = None
        if req.mode == "diff" and req.baseline_fingerprint:
            similarity = _diff_to_baseline(page, req.baseline_fingerprint)

        result = ProbeResult(
            case_id=req.case_id,
            failed_step=failed_key or steps[stop][0] if stop < len(steps) else "",
            failure_signature=sig,
            original_locator=orig,
            dom_context=dom_ctx,
            precondition_state=pre_state,
            similarity_to_baseline=similarity,
            observed_root_cause_hint=hint_msg,
            heal_layer_suggestion=layer,
            repair_tier=tier,
            notes=f"executed {executed} steps; mode={req.mode}",
        )
        # mode=hypothesis: structured experiment — planned extension (needs alt-action apply)
        if req.mode == "hypothesis":
            result.notes += " | hypothesis mode: not yet implemented (needs alt-action apply)"
        return result
    finally:
        if page is not None:
            try:
                run_teardown(case, page)
            except Exception:
                pass
        try:
            if browser:
                browser.close()
            if pw:
                pw.stop()
        except Exception:
            pass


def _diff_to_baseline(page: Page, baseline: dict) -> Optional[float]:
    """Placeholder similarity score vs author-period fingerprint. Real impl later."""
    # For now: 1.0 if baseline section_count matches current, else crude delta.
    cur = capture_precondition_state(page).get("section_count", -1)
    base = baseline.get("section_count", -1)
    if base == -1 or cur == -1:
        return None
    return round(max(0.0, 1.0 - abs(cur - base) / max(1, base)), 3)


# ============================================================================
# CLI
# ============================================================================
def main():
    ap = argparse.ArgumentParser(description="Self-heal diagnostic probe (deterministic, no AI)")
    ap.add_argument("case_id", help="case id, e.g. testT4605")
    ap.add_argument("--step", type=int, default=0, help="run up to this 0-based step index")
    ap.add_argument("--mode", choices=["capture", "hypothesis", "diff"], default="capture")
    ap.add_argument("--yaml", default=DEFAULT_YAML, help="path to the YAML file")
    ap.add_argument("--out", default=None, help="write probe_result JSON to this file")
    args = ap.parse_args()

    req = ProbeRequest(case_id=args.case_id, step_index=args.step, mode=args.mode, yaml_path=args.yaml)
    result = probe(req)
    out = result.to_json()
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"[heal_probe] wrote {args.out}")
    else:
        print(out)


if __name__ == "__main__":
    main()
