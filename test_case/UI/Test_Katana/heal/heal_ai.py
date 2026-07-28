"""
heal_ai.py — L4 long-tail repair (requirement-driven, AI-assisted).

Design (per ADR): AI is the LAST resort, never the first. Determinism handles
L0-L3. Only failures that survive L0-L3 reach here, and only then do we spend
tokens — and even then a deterministic fallback always runs first so a missing
API key never silently drops a case.

Two paths:
  1. Deterministic fallback (always): build a structured root-cause hypothesis
     + collected evidence, mark needs_human_review=True. Never invents a YAML
     patch it cannot justify.
  2. LLM path (only if HEAL_AI_KEY set): send the structured context (failed
     case + probe DOM + candidate locators + requirement text) to an
     OpenAI-compatible endpoint; parse a JSON patch. On any error, fall back.

Requirement-driven self-heal: fetch_requirement(key) pulls the Jira ticket via
tools/jira_reader so the AI can judge whether the EXPECTED behavior changed.
"""
from __future__ import annotations

import sys
import os
import json
import urllib.request

HERE = os.path.abspath(__file__)
REPO_ROOT = HERE
while not os.path.exists(os.path.join(REPO_ROOT, 'pytest.ini')) and REPO_ROOT != os.path.dirname(REPO_ROOT):
    REPO_ROOT = os.path.dirname(REPO_ROOT)
if REPO_ROOT not in sys.path:
    sys.path.append(REPO_ROOT)


def fetch_requirement(ticket_key: str | None) -> str | None:
    """Pull a Jira ticket's requirement text via tools/jira_reader. Best-effort."""
    if not ticket_key:
        return None
    try:
        sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
        import jira_reader  # type: ignore
        raw = jira_reader.fetch_issue(ticket_key)
        distilled = jira_reader.distill_issue(raw)
        return jira_reader.to_text(distilled)
    except Exception as e:  # never block the pipeline on a missing integration
        return f"[requirement fetch failed: {e}]"


def _deterministic_fallback(ctx: dict) -> dict:
    sig = ctx.get("failure_signature", "")
    cands = ctx.get("candidate_locators") or []
    hypo = []
    if sig in ("not-found", "timeout"):
        if cands:
            hypo.append("Locator drift suspected: target missing but "
                        f"{len(cands)} candidate(s) found on page.")
            hypo.append("L1 produced no confident diff (similarity below threshold) "
                        "-> needs human confirmation of the correct candidate.")
        else:
            hypo.append("Target locator missing AND no candidate found on page. "
                        "Likely structural/selector change or element removed.")
    elif sig == "assertion":
        hypo.append("Assertion failed while target locators are present -> NOT a locator "
                    "drift. Probable flow/requirement regression.")
        if ctx.get("requirement_text"):
            hypo.append("Requirement context attached: compare expected behavior against "
                        "current step sequence.")
        else:
            hypo.append("No requirement context attached. Provide Jira ticket to judge if "
                        "expected behavior changed.")
    else:
        hypo.append(f"Unclassified failure ({sig}). Needs manual investigation.")
    return {
        "root_cause_hypothesis": " ".join(hypo),
        "yaml_patch": None,
        "confidence": 0.3,
        "needs_human_review": True,
        "usage": "deterministic-fallback",
        "notes": "No AI key configured or LLM unavailable; structured evidence collected for human review.",
    }


def _llm_repair(ctx: dict) -> dict | None:
    key = os.environ.get("HEAL_AI_KEY")
    if not key:
        return None
    base = os.environ.get("HEAL_AI_BASE_URL", "https://api.openai.com/v1/chat/completions")
    model = os.environ.get("HEAL_AI_MODEL", "gpt-4o-mini")
    prompt = (
        "You are a test-automation healing assistant. Given a failed UI test case, "
        "its captured DOM, candidate locators, and (optionally) the requirement, "
        "return JSON: {\"root_cause_hypothesis\": str, \"yaml_patch\": "
        "{\"step_key\": str, \"new_value\": object} | null, \"confidence\": 0-1, "
        "\"needs_human_review\": bool}. Only propose yaml_patch if you are confident "
        "the fix is a locator/action change, never silently alter assertions.\n\n"
        f"CONTEXT:\n{json.dumps(ctx, ensure_ascii=False, indent=2)}"
    )
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }
    req = urllib.request.Request(
        base, data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            out = json.loads(resp.read().decode())
        content = out["choices"][0]["message"]["content"]
        data = json.loads(content)
        data["usage"] = "llm"
        data.setdefault("needs_human_review", True)
        return data
    except Exception as e:
        return {"_llm_error": str(e)}


def heal_ai(ctx: dict) -> dict:
    """L4 repair. Always returns a structured result; never raises."""
    llm = _llm_repair(ctx)
    if isinstance(llm, dict) and "root_cause_hypothesis" in llm:
        return llm
    # LLM unavailable/failed -> deterministic fallback (still returns full evidence)
    fb = _deterministic_fallback(ctx)
    if isinstance(llm, dict) and "_llm_error" in llm:
        fb["notes"] = (fb.get("notes", "") + " | LLM error: " + llm["_llm_error"])
    return fb


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctx", help="JSON file with decision context")
    args = ap.parse_args()
    if args.ctx:
        ctx = json.load(open(args.ctx, encoding="utf-8"))
        print(json.dumps(heal_ai(ctx), ensure_ascii=False, indent=2))
