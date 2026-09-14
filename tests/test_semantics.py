"""Unchanged semantic content: claims round-trip, LLM merge discipline, review mapping."""
import json

from paper_humanizer.lock import Claim, DocumentLock, build_lock, merge_llm_lock
from paper_humanizer.review import _VERDICT_RULES, review_revision


class _FakeProvider:
    available = True

    def __init__(self, response: str):
        self.response = response
        self.calls: list[str] = []

    def complete(self, prompt, *, system=None, temperature=0.2, max_tokens=4096):
        self.calls.append(prompt)
        return self.response


def test_claim_ledger_round_trip(sample_zh):
    lock = build_lock(sample_zh)
    lock.claims.append(Claim(id="c001", kind="causal", strength="strong",
                             text="数字化转型显著提升了供应链韧性"))
    revived = DocumentLock.from_dict(lock.to_dict())
    assert len(revived.claims) == 1
    assert revived.claims[0].id == "c001"
    assert revived.claims[0].kind == "causal"
    assert revived.claims[0].strength == "strong"
    assert revived.claims[0].text == "数字化转型显著提升了供应链韧性"
    assert revived.atoms and revived.atoms[0].canonical


def test_merge_llm_atoms_drops_fabricated_surfaces(sample_zh):
    lock = build_lock(sample_zh)
    llm = {
        "atoms": [
            {"type": "method", "surface": "固定效应", "context": "行业固定效应"},
            {"type": "term", "surface": "不存在的术语XYZ", "context": "whatever"},
        ],
        "claims": [
            {"kind": "causal", "strength": "strong",
             "text": "数字化转型通过供应网络多元化提升供应链韧性"},
            {"kind": "bogus-kind", "strength": "strong", "text": "bad"},
        ],
    }
    merged, dropped = merge_llm_lock(lock, llm, sample_zh)
    assert dropped == 2  # 1 fabricated surface + 1 invalid claim kind
    assert any(a.kind == "phrase" and a.surface == "固定效应" for a in merged.atoms)
    assert len(merged.claims) == 1
    assert merged.claims[0].kind == "causal"


def test_merge_llm_atoms_dedupes(sample_zh):
    lock = build_lock(sample_zh)
    llm = {"atoms": [{"type": "method", "surface": "固定效应"}], "claims": []}
    merged, _ = merge_llm_lock(lock, llm, sample_zh)
    assert len([a for a in merged.atoms if a.surface == "固定效应"]) == 1
    merged2, _ = merge_llm_lock(merged, llm, sample_zh)
    assert len([a for a in merged2.atoms if a.surface == "固定效应"]) == 1


def test_review_verdict_mapping():
    assert _VERDICT_RULES["weakened"] == "claim_strength_shift"
    assert _VERDICT_RULES["strengthened"] == "claim_strength_shift"
    assert _VERDICT_RULES["contradicted"] == "claim_contradicted"
    assert _VERDICT_RULES["dropped"] == "claim_dropped"


def test_review_revision_maps_verdicts_to_hard_rules(sample_zh):
    lock = build_lock(sample_zh)
    lock.claims.append(Claim(id="c001", kind="conclusion", strength="strong",
                             text="假设H1与H2均得到数据支持"))
    response = json.dumps({
        "claims": [
            {"id": "c001", "verdict": "weakened", "evidence": "或有一定提升"},
            {"id": "c999", "verdict": "added_new", "evidence": "凭空新增政策结论"},
        ],
        "naturalness": {"score": 4, "notes": "ok"},
        "academic": {"score": 4, "notes": "ok"},
        "decision": "repair",
        "repair_instructions": ["restore claim strength"],
    }, ensure_ascii=False)
    provider = _FakeProvider(response)
    result = review_revision(provider, sample_zh, sample_zh, lock)
    rules = {v["rule"] for v in result["hard_violations"]}
    assert "claim_strength_shift" in rules
    assert "new_claim_added" in rules
    assert result["decision"] == "repair"
    assert result["naturalness"]["score"] == 4
    # input isolation: the judge prompt must not contain the rewrite template body
    assert "Non-negotiable rules" not in provider.calls[0]
