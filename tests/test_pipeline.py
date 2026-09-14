"""Pipeline-level tests with a scripted fake provider (no network).

Covers: full rewrite workflow, deterministic-failure repair loop (max 2),
and the fail-safe revert-to-original policy.
"""
import json

from paper_humanizer.pipeline import run_rewrite

DOC = """## 4 实证结果

2020—2024年共调查了327家企业。值得注意的是，数字化转型显著提升了供应链韧性。
"""

GOOD = "2020—2024年共调查了327家企业。研究显示，数字化转型显著提升了供应链韧性。"

BAD = "2020—2024年共调查了237家企业。研究显示，数字化转型显著提升了供应链韧性。"


class ScriptedProvider:
    available = True

    def __init__(self, rewrite_responses):
        self.rewrite_responses = list(rewrite_responses)
        self.idx = 0

    def complete(self, prompt, *, system=None, temperature=0.2, max_tokens=4096):
        if "SEMANTIC LOCK" in prompt:
            return json.dumps({
                "atoms": [],
                "claims": [{"kind": "finding", "strength": "strong",
                            "text": "数字化转型显著提升了供应链韧性"}],
            }, ensure_ascii=False)
        if "INDEPENDENT judge" in prompt:
            return json.dumps({
                "claims": [{"id": "c001", "verdict": "entailed", "evidence": "ok"}],
                "naturalness": {"score": 4, "notes": "ok"},
                "academic": {"score": 4, "notes": "ok"},
                "decision": "pass",
                "repair_instructions": [],
            }, ensure_ascii=False)
        if "AI-flavored" in prompt:
            return json.dumps({
                "language": "zh",
                "overall": {"naturalness_score": 2, "summary": "templated"},
                "issues": [],
            }, ensure_ascii=False)
        text = self.rewrite_responses[min(self.idx, len(self.rewrite_responses) - 1)]
        self.idx += 1
        return json.dumps({"rewritten_text": text, "change_log": [], "self_check": {}},
                          ensure_ascii=False)


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_pipeline_repairs_deterministic_violation(tmp_path):
    src = _write(tmp_path, "paper.md", DOC)
    provider = ScriptedProvider([BAD, GOOD])  # first pass breaks 327→237, repair fixes it
    result = run_rewrite(src, provider)
    assert result.status == "success"
    assert result.loops_used == 1
    assert "327家" in result.final_text
    assert "237家" not in result.final_text
    assert (result.run_dir / "final.md").read_text(encoding="utf-8") == result.final_text
    assert (result.run_dir / "lock.json").is_file()
    assert (result.run_dir / "validation.json").is_file()


def test_pipeline_reverts_after_exhausted_repairs(tmp_path):
    src = _write(tmp_path, "paper.md", DOC)
    provider = ScriptedProvider([BAD, BAD, BAD])  # repairs never fix the number
    result = run_rewrite(src, provider)
    assert result.status == "reverted"
    assert result.final_text == DOC  # ORIGINAL kept, never the damaged revision
    report = (result.run_dir / "report.md").read_text(encoding="utf-8")
    assert "REVERTED" in report
    assert "atom_changed" in report


def test_pipeline_success_first_pass(tmp_path):
    src = _write(tmp_path, "paper.md", DOC)
    provider = ScriptedProvider([GOOD])
    result = run_rewrite(src, provider)
    assert result.status == "success"
    assert result.loops_used == 0
    assert "值得注意的是" not in result.final_text  # de-templatized
    assert "327家" in result.final_text
