"""Deterministic text statistics and AI-style markers (Layer 2 diagnosis)."""
from __future__ import annotations

import json
import re
from collections import Counter

from paper_humanizer import paths
from paper_humanizer.errors import ConfigError
from paper_humanizer.normalize import sentence_spans

_MARKERS_CACHE: dict | None = None


def load_markers() -> dict:
    global _MARKERS_CACHE
    if _MARKERS_CACHE is None:
        path = paths.markers_path()
        if not path.is_file():
            raise ConfigError(f"markers file not found: {path}")
        _MARKERS_CACHE = json.loads(path.read_text(encoding="utf-8"))
    return _MARKERS_CACHE


def detect_language(text: str) -> str:
    if not text:
        return "en"
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    return "zh" if cjk / max(1, len(text)) >= 0.10 else "en"


def compute_stats(text: str, markers: dict | None = None, language: str | None = None) -> dict:
    markers = markers if markers is not None else load_markers()
    lang = language or detect_language(text)

    spans = sentence_spans(text)
    lengths = [e - s for s, e in spans]
    n_sentences = len(lengths)
    mean = sum(lengths) / n_sentences if n_sentences else 0.0
    variance = sum((x - mean) ** 2 for x in lengths) / n_sentences if n_sentences else 0.0
    sd = variance ** 0.5
    cv = sd / mean if mean else 0.0

    paragraphs = [p for p in re.split(r"\n{2,}", text) if p.strip()]
    para_lengths = [len(p) for p in paragraphs]

    other = "en" if lang == "zh" else "zh"
    lower = text.lower()
    hits: list[dict] = []
    total_hits = 0
    for source_lang in (lang, other):
        for phrase in markers[source_lang]["template_phrases"]:
            count = lower.count(phrase.lower())
            if count:
                hits.append({"phrase": phrase, "count": count, "lang": source_lang})
                total_hits += count
    hits.sort(key=lambda h: -h["count"])

    chains = []
    for i, para in enumerate(paragraphs):
        found: list[str] = []
        for source_lang in (lang, other):
            found += [m for m in markers[source_lang]["chain_markers"] if m in para]
        distinct = sorted(set(found))
        if len(distinct) >= 2:
            chains.append({"paragraph": i + 1, "markers": distinct})

    connective_counts = Counter()
    for conn in markers[lang]["connectives"] + markers[other]["connectives"]:
        count = lower.count(conn.lower())
        if count:
            connective_counts[conn] += count
    total_conn = sum(connective_counts.values())
    top_share = (max(connective_counts.values()) / total_conn) if total_conn else 0.0

    banned = []
    for source_lang in (lang, other):
        for phrase in markers[source_lang].get("banned_register", []):
            count = lower.count(phrase.lower())
            if count:
                banned.append({"phrase": phrase, "count": count})

    openings = Counter(p.strip()[:6] for p in paragraphs if len(p.strip()) >= 10)
    opening_top = (max(openings.values()) / len(openings)) if openings else 0.0

    if lang == "zh":
        density = total_hits / max(1, len(text)) * 1000
        unit = "1k_chars"
        high, mid = 5.0, 2.5
    else:
        words = len(re.findall(r"[A-Za-z]+", text))
        density = total_hits / max(1, words) * 1000
        unit = "1k_words"
        high, mid = 10.0, 4.0

    if density >= high or (density >= mid and cv < 0.35):
        level = "high"
    elif density >= mid or cv < 0.35:
        level = "medium"
    else:
        level = "low"

    return {
        "chars": len(text),
        "n_sentences": n_sentences,
        "sentence_mean": round(mean, 2),
        "sentence_sd": round(sd, 2),
        "sentence_cv": round(cv, 3),
        "n_paragraphs": len(paragraphs),
        "paragraph_mean": round(sum(para_lengths) / len(para_lengths), 1) if para_lengths else 0,
        "template_hits": hits,
        "template_hits_total": total_hits,
        "template_density": round(density, 2),
        "density_unit": unit,
        "chains": chains,
        "connective_top_share": round(top_share, 3),
        "banned_register_hits": banned,
        "opening_top_share": round(opening_top, 3),
        "ai_style_level": level,
    }
