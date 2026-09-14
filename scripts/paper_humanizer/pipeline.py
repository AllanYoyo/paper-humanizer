"""Full rewrite pipeline.

Workflow: normalize → diagnose → semantic lock → section-aware rewrite →
deterministic validation → LLM review → repair (max 2 loops) → final output.

Failure policy: if hard violations persist after the repair budget, the
ORIGINAL text is kept and the failure reasons are reported — a revised text
with unresolved semantic damage is never emitted.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from paper_humanizer.diagnose import diagnose_document
from paper_humanizer.errors import ProviderError, ProviderNotConfigured, PromptError
from paper_humanizer.extract import KIND_PHRASE, KIND_TERM, KIND_VAR
from paper_humanizer.lock import (
    DocumentLock,
    build_lock,
    load_glossary_for,
    merge_llm_lock,
)
from paper_humanizer.normalize import normalize_document
from paper_humanizer.prompts_loader import ask_json
from paper_humanizer.review import review_revision
from paper_humanizer.segment import Block, assemble, segment_document
from paper_humanizer.stats import detect_language
from paper_humanizer.validate import ValidationReport, validate_document

MIN_REWRITE_CHARS = 40


@dataclass
class PipelineResult:
    status: str  # "success" | "reverted"
    final_text: str
    revised_text: str
    report_md: str
    run_dir: Path
    loops_used: int
    validation: ValidationReport
    review: dict | None
    warnings: list[str] = field(default_factory=list)
    artifacts: list[Path] = field(default_factory=list)


def build_enriched_lock(original_text: str, input_path: Path, provider,
                        warnings: list[str]) -> DocumentLock:
    """Regex lock + optional channel-B (LLM) atoms and claims."""
    glossary = load_glossary_for(input_path)
    lock = build_lock(original_text, source=str(input_path), glossary=glossary)
    if provider is not None and getattr(provider, "available", False):
        try:
            llm = ask_json(provider, "semantic-lock", {
                "text": original_text[:12000],
                "regex_atoms": json.dumps(
                    [{"type": a.kind, "surface": a.surface} for a in lock.atoms],
                    ensure_ascii=False)[:4000],
                "glossary": ", ".join(glossary) if glossary else "(none)",
            })
            lock, dropped = merge_llm_lock(lock, llm, original_text)
            if dropped:
                warnings.append(
                    f"{dropped} LLM-proposed atoms/claims dropped (fabricated or invalid)")
        except (ProviderError, PromptError) as exc:
            warnings.append(f"LLM lock enrichment skipped: {exc}")
    return lock


def _rewrite_block(provider, lang: str, section, block: Block, lock: DocumentLock,
                   issues_text: str, instructions: str) -> str:
    lock_slice = [
        {"id": a.id, "kind": a.kind, "surface": a.surface, "canonical": a.canonical}
        for a in lock.atoms
        if (a.start >= 0 and block.start <= a.start < block.end)
        or a.kind in (KIND_TERM, KIND_VAR, KIND_PHRASE)
    ]
    claims = [{"id": c.id, "kind": c.kind, "strength": c.strength, "text": c.text}
              for c in lock.claims]
    data = ask_json(provider, "rewrite", {
        "language": lang,
        "section_type": section.section_type,
        "section_text": block.text,
        "lock_atoms": json.dumps(lock_slice, ensure_ascii=False),
        "claims": json.dumps(claims, ensure_ascii=False),
        "issues": issues_text,
        "repair_instructions": instructions or "(none)",
    })
    text = str(data.get("rewritten_text", "")).strip()
    if not text:
        raise PromptError("rewritten_text is empty")
    # Assembly fidelity: keep the block's original leading/trailing whitespace
    # (e.g. the newline after a heading) so the document shape is unchanged.
    lead = block.text[:len(block.text) - len(block.text.lstrip())]
    trail = block.text[len(block.text.rstrip()):]
    return lead + text + trail


def _rewrite_units(provider, units, lang: str, lock: DocumentLock, issues_text: str,
                   instructions: str, warnings: list[str],
                   current: dict[int, str]) -> dict[int, str]:
    out: dict[int, str] = {}
    for section, block in units:
        text_now = current.get(block.index, block.text)
        if len(text_now.strip()) < MIN_REWRITE_CHARS:
            continue
        probe = Block("prose", text_now, block.start, block.end, block.index)
        try:
            out[block.index] = _rewrite_block(provider, lang, section, probe, lock,
                                              issues_text, instructions)
        except (ProviderError, PromptError) as exc:
            warnings.append(f"rewrite of block {block.index} failed, kept current text: {exc}")
    return out


def _repair_instructions(report: ValidationReport) -> str:
    lines = []
    for v in report.hard_violations:
        context = f"（原文: {v.before[:60]}）" if v.before else ""
        after = f"（改写后: {v.after[:60]}）" if v.after else ""
        lines.append(f"- 违规 {v.rule}: {v.detail} {context}{after}")
    lines.append("修复时只做最小必要修改，逐条解决上述违规；不得引入新的数字、引用或术语变化。")
    return "\n".join(lines)


def _affected_units(units, report: ValidationReport, current: dict[int, str]) -> list:
    quotes = [v.before.strip()[:40] for v in report.hard_violations if v.before.strip()]
    quotes += [v.after.strip()[:40] for v in report.hard_violations if v.after.strip()]
    quotes = [q for q in quotes if q]
    if not quotes:
        return units
    affected = []
    for section, block in units:
        text_now = current.get(block.index, block.text)
        if any(q in text_now or q in block.text for q in quotes):
            affected.append((section, block))
    return affected or units


def run_rewrite(input_path: Path, provider, *, max_repairs: int = 2) -> PipelineResult:
    if not getattr(provider, "available", False):
        raise ProviderNotConfigured(
            "rewrite requires an LLM provider: set PAPER_HUMANIZER_API_KEY, "
            "PAPER_HUMANIZER_BASE_URL and PAPER_HUMANIZER_MODEL "
            "(or run in agent mode — see SKILL.md)"
        )
    warnings: list[str] = []
    original = normalize_document(input_path.read_text(encoding="utf-8"))
    lang = detect_language(original)

    issues_text = ""
    diag: dict = {}
    try:
        diag = diagnose_document(original, provider=provider)
        if diag.get("qualitative"):
            issues_text = json.dumps(diag["qualitative"], ensure_ascii=False)[:2000]
    except (ProviderError, PromptError) as exc:
        warnings.append(f"diagnosis LLM step skipped: {exc}")

    lock = build_enriched_lock(original, input_path, provider, warnings)
    seg = segment_document(original)
    units = [(sec, b) for sec in seg.sections for b in sec.blocks
             if b.kind == "prose" and len(b.text.strip()) >= MIN_REWRITE_CHARS]

    replacements: dict[int, str] = {}
    replacements.update(_rewrite_units(provider, units, lang, lock, issues_text,
                                       "", warnings, replacements))
    revised = assemble(seg, replacements)

    loops = 0
    report = validate_document(lock, revised)
    while report.hard_violations and loops < max_repairs:
        loops += 1
        affected = _affected_units(units, report, replacements)
        replacements.update(_rewrite_units(
            provider, affected, lang, lock, issues_text,
            _repair_instructions(report), warnings, replacements))
        revised = assemble(seg, replacements)
        report = validate_document(lock, revised)

    review_data: dict | None = None
    claim_hard: list[dict] = []
    if not report.hard_violations:
        try:
            review_data = review_revision(provider, original, revised, lock)
            claim_hard = review_data["hard_violations"]
            if claim_hard and loops < max_repairs:
                loops += 1
                instructions = "\n".join(v["detail"] for v in claim_hard)
                instructions += "\n" + "\n".join(
                    str(x) for x in review_data["review"].get("repair_instructions", []) if x
                )
                replacements.update(_rewrite_units(
                    provider, units, lang, lock, issues_text, instructions,
                    warnings, replacements))
                revised = assemble(seg, replacements)
                report = validate_document(lock, revised)
                if not report.hard_violations:
                    review_data = review_revision(provider, original, revised, lock)
                    claim_hard = review_data["hard_violations"]
        except (ProviderError, PromptError) as exc:
            warnings.append(f"review skipped: {exc}")

    hard = report.hard_violations or claim_hard
    status = "success" if not hard else "reverted"
    final_text = original if status == "reverted" else revised

    run_dir = input_path.resolve().parent / ".paper-humanizer" / "runs" / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[Path] = []

    def _write(name: str, content: str) -> None:
        path = run_dir / name
        path.write_text(content, encoding="utf-8")
        artifacts.append(path)

    _write("original.md", original)
    _write("lock.json", lock.dump())
    if diag:
        _write("diagnosis.json", json.dumps(diag, ensure_ascii=False, indent=2))
    _write("validation.json", json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    if review_data:
        _write("review.json", json.dumps(review_data.get("review", {}), ensure_ascii=False, indent=2))
    _write("revised_attempt.md", revised)
    _write("final.md", final_text)

    from paper_humanizer.report import render_report

    report_md = render_report(
        status=status, input_name=input_path.name, loops=loops,
        report=report, review=review_data, warnings=warnings,
        artifacts=artifacts, final_name="final.md",
    )
    _write("report.md", report_md)

    return PipelineResult(
        status=status, final_text=final_text, revised_text=revised,
        report_md=report_md, run_dir=run_dir, loops_used=loops,
        validation=report, review=review_data, warnings=warnings, artifacts=artifacts,
    )
