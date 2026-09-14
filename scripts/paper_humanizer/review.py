"""Semantic preservation review (Layer 1 judge) with Layer 2 bookkeeping.

The judge only sees the original, the revision, and the registered claims —
never the rewrite instructions (input isolation). Its verdicts are mapped to
hard-fail rules; its evidence quotes are NOT trusted blindly but the
deterministic lock already covers everything countable.
"""
from __future__ import annotations

import json

from paper_humanizer.errors import ProviderError, PromptError
from paper_humanizer.lock import DocumentLock
from paper_humanizer.prompts_loader import ask_json

_VERDICT_RULES = {
    "weakened": "claim_strength_shift",
    "strengthened": "claim_strength_shift",
    "contradicted": "claim_contradicted",
    "dropped": "claim_dropped",
}


def review_revision(provider, original_text: str, revised_text: str, lock: DocumentLock) -> dict:
    claims_payload = [
        {"id": c.id, "kind": c.kind, "strength": c.strength, "text": c.text}
        for c in lock.claims
    ]
    data = ask_json(
        provider, "review",
        {
            "original_text": original_text[:9000],
            "revised_text": revised_text[:9000],
            "claims_json": json.dumps(claims_payload, ensure_ascii=False),
        },
    )
    hard: list[dict] = []
    seen: set[str] = set()
    claim_items = data.get("claims", []) if isinstance(data, dict) else []
    if not isinstance(claim_items, list):
        claim_items = []
    for item in claim_items:
        if not isinstance(item, dict):
            continue
        claim_id = str(item.get("id", ""))
        verdict = str(item.get("verdict", "")).lower().strip()
        seen.add(claim_id)
        evidence = str(item.get("evidence", ""))[:160]
        if verdict == "added_new":
            hard.append({"claim_id": claim_id, "rule": "new_claim_added",
                         "detail": f"改写新增了原文没有的论断（claim {claim_id}）: {evidence}"})
        elif verdict in _VERDICT_RULES:
            hard.append({"claim_id": claim_id, "rule": _VERDICT_RULES[verdict],
                         "detail": f"claim {claim_id} 判定为 {verdict}: {evidence}"})
    registered = {c.id for c in lock.claims}
    return {
        "review": data,
        "hard_violations": hard,
        "unreviewed_claims": sorted(registered - seen),
        "naturalness": data.get("naturalness", {}) if isinstance(data, dict) else {},
        "academic": data.get("academic", {}) if isinstance(data, dict) else {},
        "decision": str(data.get("decision", "pass")).lower() if isinstance(data, dict) else "pass",
    }


def review_single_document(provider, text: str) -> dict:
    """Qualitative review of a standalone document (no revision to compare)."""
    from paper_humanizer.diagnose import diagnose_document

    diagnosis = diagnose_document(text, provider=provider)
    return {"diagnosis": diagnosis}
