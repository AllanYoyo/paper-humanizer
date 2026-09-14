"""AI-style diagnosis: deterministic statistics + optional LLM qualitative pass."""
from __future__ import annotations

import json

from paper_humanizer.errors import ProviderError, PromptError
from paper_humanizer.normalize import normalize_document
from paper_humanizer.stats import compute_stats, detect_language


def diagnose_document(text: str, provider=None) -> dict:
    text_n = normalize_document(text)
    language = detect_language(text_n)
    stats = compute_stats(text_n, language=language)
    result: dict = {
        "schema_version": "1.0",
        "language": language,
        "stats": stats,
        "qualitative": None,
        "notes": [],
    }
    if provider is not None and getattr(provider, "available", False):
        try:
            from paper_humanizer.prompts_loader import ask_json

            result["qualitative"] = ask_json(
                provider, "diagnosis",
                {
                    "language": language,
                    "text": text_n[:8000],
                    "stats_summary": json.dumps(stats, ensure_ascii=False)[:1500],
                },
            )
        except (ProviderError, PromptError) as exc:
            result["notes"].append(f"qualitative diagnosis skipped: {exc}")
    else:
        result["notes"].append("qualitative diagnosis skipped: no LLM provider configured")
    return result


def render_diagnosis(result: dict) -> str:
    stats = result["stats"]
    lines = [
        "== paper-humanizer diagnosis ==",
        f"language: {result['language']}  chars: {stats['chars']}  "
        f"sentences: {stats['n_sentences']}  paragraphs: {stats['n_paragraphs']}",
        f"sentence length: mean {stats['sentence_mean']}  sd {stats['sentence_sd']}  cv {stats['sentence_cv']}",
        f"template phrases: {stats['template_hits_total']} hits "
        f"({stats['template_density']}/1k {stats['density_unit']})  "
        f"-> ai-style level: {stats['ai_style_level'].upper()}",
    ]
    if stats["template_hits"]:
        top = ", ".join(f"{h['phrase']}×{h['count']}" for h in stats["template_hits"][:8])
        lines.append(f"  top: {top}")
    if stats["chains"]:
        lines.append(f"mechanical chains (首先/其次/最后 or first/second/finally): {len(stats['chains'])} paragraph(s)")
    if stats["banned_register_hits"]:
        lines.append(f"register issues: {stats['banned_register_hits']}")
    for note in result["notes"]:
        lines.append(f"note: {note}")
    qualitative = result["qualitative"]
    if isinstance(qualitative, dict):
        overall = qualitative.get("overall", {})
        lines.append(f"LLM naturalness: {overall.get('naturalness_score', '?')}/5 — "
                     f"{str(overall.get('summary', ''))[:140]}")
        for issue in qualitative.get("issues", [])[:8]:
            if isinstance(issue, dict):
                lines.append(f"  [{issue.get('severity', '?')}] {issue.get('type', '?')}: "
                             f"{str(issue.get('evidence_quote', ''))[:60]}")
    return "\n".join(lines)
