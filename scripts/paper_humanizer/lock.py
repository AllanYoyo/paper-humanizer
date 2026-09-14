"""Semantic lock manifest: build, merge LLM extractions, serialize.

The lock is the machine-checkable inventory of everything that must survive
rewriting. Regex extraction (Layer 2) is the enforcement backbone; the LLM
(channel B) adds high-recall atoms and claims, but every LLM surface is
verified to exist in the text before it enters the lock (meta-validation).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from paper_humanizer.extract import (
    KIND_AMOUNT,
    KIND_COEF,
    KIND_COUNT,
    KIND_CITE_AY,
    KIND_CITE_NUM,
    KIND_DATE,
    KIND_DOI,
    KIND_NUMBER,
    KIND_PHRASE,
    KIND_PVALUE,
    KIND_RANGE,
    KIND_SIG,
    KIND_TERM,
    KIND_URL,
    KIND_VAR,
    Atom,
    extract_atoms,
)
from paper_humanizer.normalize import collapse_ws, normalize_document
from paper_humanizer.segment import mask_for_extraction, segment_document

LOCK_SCHEMA_VERSION = "1.0"

KIND_ALIASES: dict[str, str] = {
    "number": KIND_NUMBER,
    "percent": "percent",
    "amount": KIND_AMOUNT,
    "date": KIND_DATE,
    "range": KIND_RANGE,
    "count": KIND_COUNT,
    "p_value": KIND_PVALUE,
    "significance": KIND_SIG,
    "coefficient": KIND_COEF,
    "citation": KIND_CITE_NUM,
    "citation_ay": KIND_CITE_AY,
    "url": KIND_URL,
    "doi": KIND_DOI,
    "term": KIND_TERM,
    "variable": KIND_VAR,
    "method": KIND_PHRASE,
    "condition": KIND_PHRASE,
    "source": KIND_PHRASE,
    "phrase": KIND_PHRASE,
}

CLAIM_KINDS = {"finding", "conclusion", "causal", "attribution", "stance"}
CLAIM_STRENGTHS = {"strong", "moderate", "hedged", "neutral"}


@dataclass
class Claim:
    id: str
    kind: str
    strength: str
    text: str


@dataclass
class DocumentLock:
    schema_version: str = LOCK_SCHEMA_VERSION
    source: str = "<memory>"
    language: str = "zh"
    atoms: list[Atom] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)
    glossary: list[str] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)
    source_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "language": self.language,
            "atoms": [
                {"id": a.id, "kind": a.kind, "surface": a.surface,
                 "canonical": a.canonical, "context": a.context}
                for a in self.atoms
            ],
            "claims": [
                {"id": c.id, "kind": c.kind, "strength": c.strength, "text": c.text}
                for c in self.claims
            ],
            "terms": self.terms,
            "glossary": self.glossary,
            "headings": self.headings,
            "tables": self.tables,
            "codes": self.codes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DocumentLock":
        lock = cls(
            schema_version=data.get("schema_version", LOCK_SCHEMA_VERSION),
            source=data.get("source", "<memory>"),
            language=data.get("language", "zh"),
            terms=list(data.get("terms", [])),
            glossary=list(data.get("glossary", [])),
            headings=list(data.get("headings", [])),
            tables=list(data.get("tables", [])),
            codes=list(data.get("codes", [])),
            source_text="",
        )
        for a in data.get("atoms", []):
            lock.atoms.append(Atom(
                id=a.get("id", ""), kind=a.get("kind", ""), surface=a.get("surface", ""),
                canonical=a.get("canonical", ""), context=a.get("context", ""),
            ))
        for c in data.get("claims", []):
            lock.claims.append(Claim(
                id=c.get("id", ""), kind=c.get("kind", "finding"),
                strength=c.get("strength", "hedged"), text=c.get("text", ""),
            ))
        return lock

    def dump(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def build_lock(text: str, *, source: str = "<memory>", glossary: list[str] | None = None) -> DocumentLock:
    """Regex-only lock build (fully deterministic; used by ``validate`` too)."""
    text_n = normalize_document(text)
    seg = segment_document(text_n)
    masked = mask_for_extraction(text_n, seg)
    glossary = [g.strip() for g in (glossary or []) if g.strip()]
    atoms = extract_atoms(masked, text_n, glossary=glossary)
    for i, atom in enumerate(atoms, 1):
        atom.id = f"a{i:03d}"
    return DocumentLock(
        source=source,
        language=_detect_language(text_n),
        atoms=atoms,
        glossary=glossary,
        terms=[a.surface for a in atoms if a.kind == "term"],
        headings=list(seg.headings),
        tables=[list(t) for t in seg.tables],
        codes=list(seg.codes),
        source_text=text_n,
    )


def _detect_language(text: str) -> str:
    if not text:
        return "en"
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    return "zh" if cjk / max(1, len(text)) >= 0.10 else "en"


def _canonical_for_surface(kind: str, surface: str) -> str:
    """Re-derive a canonical value from an LLM-provided surface via the regex extractor."""
    sub = extract_atoms(surface, surface)
    for atom in sub:
        if atom.kind == kind:
            return atom.canonical
    for atom in sub:  # numeric near-miss: LLM said "count", regex saw "number"
        if atom.kind in {KIND_NUMBER, "percent", KIND_COUNT, KIND_AMOUNT, KIND_DATE, KIND_RANGE, KIND_PVALUE, KIND_SIG, KIND_COEF}:
            if kind in {KIND_NUMBER, "percent", KIND_COUNT, KIND_AMOUNT, KIND_DATE, KIND_RANGE, KIND_PVALUE, KIND_SIG, KIND_COEF}:
                return atom.canonical
    return f"{kind.upper()}({surface})"


def merge_llm_lock(lock: DocumentLock, llm: Any, original_text: str) -> tuple[DocumentLock, int]:
    """Merge channel-B (LLM) atoms and claims into the lock.

    Every LLM surface must be a verbatim (whitespace-insensitive) substring of
    the text; fabricated surfaces are dropped and counted. Returns (lock, dropped).
    """
    flat = collapse_ws(normalize_document(original_text))
    existing_keys = {(a.kind, a.canonical) for a in lock.atoms}
    existing_surfaces = {collapse_ws(a.surface) for a in lock.atoms}
    next_id = len(lock.atoms) + 1
    dropped = 0

    atoms = llm.get("atoms", []) if isinstance(llm, dict) else []
    if not isinstance(atoms, list):
        atoms = []
    for item in atoms:
        if not isinstance(item, dict):
            dropped += 1
            continue
        surface = str(item.get("surface", "")).strip()
        if not surface or collapse_ws(surface) not in flat:
            dropped += 1
            continue
        if collapse_ws(surface) in existing_surfaces:
            continue  # already covered by regex extraction
        kind = KIND_ALIASES.get(str(item.get("type", "phrase")).lower().strip(), KIND_PHRASE)
        canonical = _canonical_for_surface(kind, surface)
        if (kind, canonical) in existing_keys:
            continue
        lock.atoms.append(Atom(
            id=f"a{next_id:03d}", kind=kind, surface=surface, canonical=canonical,
            context=str(item.get("context", surface))[:200],
        ))
        existing_keys.add((kind, canonical))
        existing_surfaces.add(collapse_ws(surface))
        next_id += 1

    claims = llm.get("claims", []) if isinstance(llm, dict) else []
    if not isinstance(claims, list):
        claims = []
    for item in claims:
        if not isinstance(item, dict):
            dropped += 1
            continue
        kind = str(item.get("kind", "finding")).lower().strip()
        text = str(item.get("text", "")).strip()
        if kind not in CLAIM_KINDS or not text:
            dropped += 1
            continue
        strength = str(item.get("strength", "hedged")).lower().strip()
        lock.claims.append(Claim(
            id=f"c{len(lock.claims) + 1:03d}", kind=kind,
            strength=strength if strength in CLAIM_STRENGTHS else "hedged", text=text,
        ))
    return lock, dropped


def load_glossary_for(input_path) -> list[str]:
    """Load optional '<stem>.glossary.txt' next to the input (one term per line)."""
    glossary_path = input_path.with_suffix(".glossary.txt")
    if not glossary_path.is_file():
        return []
    terms = []
    for line in glossary_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            terms.append(line)
    return terms
