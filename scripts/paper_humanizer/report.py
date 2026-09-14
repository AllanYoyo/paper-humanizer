"""Markdown report rendering from templates/report.md."""
from __future__ import annotations

import string

from paper_humanizer import paths
from paper_humanizer.validate import ValidationReport


def render_report(*, status: str, input_name: str, loops: int,
                  report: ValidationReport, review: dict | None,
                  warnings: list[str], artifacts, final_name: str) -> str:
    template_dir = paths.require_dir(paths.templates_dir(), "templates directory")
    template = string.Template((template_dir / "report.md").read_text(encoding="utf-8"))

    scores = [f"- semantic_fidelity / atom preserved rate: {report.preserved_rate:.2%}"]
    decision = "n/a (no LLM review)"
    if review:
        naturalness = review.get("naturalness") or {}
        academic = review.get("academic") or {}
        scores.append(f"- naturalness (LLM judge): {naturalness.get('score', 'n/a')}/5")
        scores.append(f"- academic (LLM judge): {academic.get('score', 'n/a')}/5")
        decision = str(review.get("decision", "pass"))
    scores.append(f"- review decision: {decision}")

    failures = [f"- [{v.severity}] {v.rule}: {v.detail}" for v in report.violations]
    if review:
        failures += [f"- [hard] {v['rule']}: {v['detail']}" for v in review.get("hard_violations", [])]

    notes = [f"- {w}" for w in warnings]
    if review and review.get("unreviewed_claims"):
        notes.append("- claims without verdict (review incomplete): "
                     + ", ".join(review["unreviewed_claims"]))

    return template.safe_substitute(
        STATUS=status.upper(),
        INPUT=input_name,
        OUTPUT=final_name,
        LOOPS=str(loops),
        SCORES="\n".join(scores),
        FAILURES="\n".join(failures) if failures else "- (none)",
        NOTES="\n".join(notes) if notes else "- (none)",
        ARTIFACTS="\n".join(f"- {p}" for p in artifacts),
    )
