"""Deterministic semantic-lock validation (Layer 2 gate).

Re-extracts atoms from the revised text with the SAME extractor that built the
lock (symmetry principle), diffs them against the lock, and classifies hard
failures. Never uses an LLM: judges judge meaning, scripts count facts.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from paper_humanizer.extract import (
    KIND_AMOUNT,
    KIND_CITE_AY,
    KIND_CITE_NUM,
    KIND_COEF,
    KIND_COUNT,
    KIND_DATE,
    KIND_DOI,
    KIND_NUMBER,
    KIND_PERCENT,
    KIND_PVALUE,
    KIND_RANGE,
    KIND_SIG,
    KIND_URL,
    Atom,
)
from paper_humanizer.extract import extract_atoms
from paper_humanizer.lock import DocumentLock
from paper_humanizer.normalize import collapse_ws, normalize_document
from paper_humanizer.segment import SegmentResult, frozen_inventory, mask_for_extraction, segment_document

HARD = "hard"
SOFT = "soft"

KINDS_EXCLUDED_FROM_ADDED = {KIND_CITE_NUM, KIND_CITE_AY, KIND_URL, KIND_DOI, "term", "variable", "phrase"}


@dataclass
class Violation:
    rule: str
    severity: str
    detail: str
    before: str = ""
    after: str = ""

    def to_dict(self) -> dict:
        return {"rule": self.rule, "severity": self.severity,
                "detail": self.detail, "before": self.before, "after": self.after}


@dataclass
class ValidationReport:
    violations: list[Violation] = field(default_factory=list)
    atom_results: list[dict] = field(default_factory=list)
    preserved_rate: float = 1.0
    passed: bool = True
    stats: dict = field(default_factory=dict)

    @property
    def hard_violations(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == HARD]

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "preserved_rate": round(self.preserved_rate, 4),
            "violations": [v.to_dict() for v in self.violations],
            "atom_results": self.atom_results,
            "stats": self.stats,
        }


_P_BRIDGE = re.compile(r"^P\((lt|le),(.+)\)$")


def _flatten_cited_numbers(atoms: list[Atom]) -> list[int]:
    nums: list[int] = []
    for a in atoms:
        if a.kind == KIND_CITE_NUM:
            inner = a.canonical[len("CITES("):-1]
            nums.extend(int(x) for x in inner.split(",") if x)
    return nums


def _number_in_source(atom: Atom, source_text: str) -> bool:
    m = re.search(r"\d+(?:\.\d+)?", atom.canonical)
    if not m:
        return False
    source_numbers = set(re.findall(r"\d+(?:\.\d+)?", source_text))
    return m.group(0) in source_numbers


def _norm_cell(c: str) -> str:
    return re.sub(r"\s+", " ", c).strip()


def _norm_table(table: list[list[str]]) -> list[list[str]]:
    return [[_norm_cell(c) for c in row] for row in table]


def _bridge_match(atom: Atom, buckets: dict[tuple[str, str], list[Atom]]) -> Atom | None:
    """SIG(0.01) ≡ P(lt|le,0.01): '在1%水平上显著' and 'p<0.01' state the same fact."""
    if atom.kind == KIND_SIG:
        value = atom.canonical[len("SIG("):-1]
        for op in ("lt", "le"):
            key = (KIND_PVALUE, f"P({op},{value})")
            if buckets.get(key):
                return buckets[key].pop(0)
    elif atom.kind == KIND_PVALUE:
        m = _P_BRIDGE.match(atom.canonical)
        if m:
            key = (KIND_SIG, f"SIG({m.group(2)})")
            if buckets.get(key):
                return buckets[key].pop(0)
    return None


def validate_document(lock: DocumentLock, revised_raw: str) -> ValidationReport:
    revised = normalize_document(revised_raw)
    seg: SegmentResult = segment_document(revised)
    masked = mask_for_extraction(revised, seg)
    rev_atoms = extract_atoms(masked, revised, glossary=lock.glossary)

    buckets: dict[tuple[str, str], list[Atom]] = {}
    for a in rev_atoms:
        buckets.setdefault(a.key, []).append(a)

    violations: list[Violation] = []
    atom_results: list[dict] = []
    missing: list[Atom] = []

    dedicated = {KIND_CITE_NUM, KIND_CITE_AY, KIND_URL, KIND_DOI}
    for atom in lock.atoms:
        record = {"id": atom.id, "kind": atom.kind, "surface": atom.surface,
                  "canonical": atom.canonical, "verdict": "missing", "matched": "",
                  "dedicated": atom.kind in dedicated}
        if atom.kind in dedicated:
            atom_results.append(record)
            continue
        bucket = buckets.get(atom.key)
        if bucket:
            got = bucket.pop(0)
            record["verdict"] = "preserved" if collapse_ws(got.surface) == collapse_ws(atom.surface) else "equivalent"
            record["matched"] = got.surface
        else:
            bridged = _bridge_match(atom, buckets)
            if bridged is not None:
                record["verdict"] = "equivalent"
                record["matched"] = bridged.surface
            else:
                missing.append(atom)
        atom_results.append(record)

    added: list[Atom] = []
    for key, bucket in buckets.items():
        if key[0] in KINDS_EXCLUDED_FROM_ADDED:
            continue
        added.extend(bucket)

    numeric_kinds = {KIND_NUMBER, KIND_PERCENT, KIND_AMOUNT, KIND_DATE, KIND_RANGE,
                     KIND_COUNT, KIND_PVALUE, KIND_SIG, KIND_COEF}
    for kind in sorted(numeric_kinds):
        miss = [a for a in missing if a.kind == kind]
        extra = [a for a in added if a.kind == kind]
        pairs = min(len(miss), len(extra))
        for i in range(pairs):
            violations.append(Violation(
                "atom_changed", HARD,
                f"{kind}: '{miss[i].surface}' 被改为 '{extra[i].surface}'",
                miss[i].context, extra[i].context))
        for a in miss[pairs:]:
            violations.append(Violation(
                "atom_missing", HARD, f"{kind}: '{a.surface}' 在改写后消失", a.context, ""))
        for a in extra[pairs:]:
            if kind == KIND_NUMBER and _number_in_source(a, lock.source_text):
                violations.append(Violation(
                    "numeric_added_warning", SOFT,
                    f"出现数值 '{a.surface}'（该数值在原文其他位置出现，降级为提示）", "", a.context))
            else:
                violations.append(Violation(
                    "new_data_atom", HARD,
                    f"出现原文不存在的{kind}: '{a.surface}'", "", a.context))

    lock_nums = Counter(_flatten_cited_numbers(lock.atoms))
    rev_nums = Counter(_flatten_cited_numbers(rev_atoms))
    for num, count in (lock_nums - rev_nums).items():
        violations.append(Violation("citation_lost", HARD, f"引用 [{num}] 丢失 ×{count}"))
    for num, count in (rev_nums - lock_nums).items():
        violations.append(Violation("citation_added", HARD, f"出现原文没有的引用 [{num}] ×{count}"))

    lock_ay = {a.canonical for a in lock.atoms if a.kind == KIND_CITE_AY}
    rev_ay = {a.canonical for a in rev_atoms if a.kind == KIND_CITE_AY}
    for c in lock_ay - rev_ay:
        violations.append(Violation("citation_lost", HARD, f"作者-年份引用丢失: {c}"))
    for c in rev_ay - lock_ay:
        violations.append(Violation("citation_added", HARD, f"出现原文没有的作者-年份引用: {c}"))

    for kind in (KIND_URL, KIND_DOI):
        lock_keys = {a.key for a in lock.atoms if a.kind == kind}
        rev_keys = {a.key for a in rev_atoms if a.kind == kind}
        for k in lock_keys - rev_keys:
            violations.append(Violation("doi_url_changed", HARD, f"{kind} 丢失或被改变: {k[1]}"))
        for k in rev_keys - lock_keys:
            violations.append(Violation("doi_url_changed", HARD, f"出现新的 {kind}: {k[1]}"))

    for atom in lock.atoms:
        if atom.kind == "term":
            term = atom.canonical[len("TERM("):-1]
            if term not in revised:
                violations.append(Violation(
                    "term_drift", HARD,
                    f"关键术语变化: '{term}' 未在改写文中出现", atom.context, ""))

    if lock.headings != seg.headings:
        violations.append(Violation(
            "structure_broken", HARD,
            f"标题结构变化: {lock.headings} -> {seg.headings}"))

    if len(lock.tables) != len(seg.tables):
        violations.append(Violation("frozen_region_modified", HARD,
                                    f"表格数量变化: {len(lock.tables)} -> {len(seg.tables)}"))
    else:
        for i, (t_lock, t_rev) in enumerate(zip(lock.tables, seg.tables)):
            if _norm_table(t_lock) != _norm_table(t_rev):
                violations.append(Violation(
                    "frozen_region_modified", HARD,
                    f"表{i + 1} 单元格值被修改（冻结区域）"))
    if lock.codes != seg.codes:
        violations.append(Violation("frozen_region_modified", HARD,
                                    "代码/公式块被修改（冻结区域）"))

    checkable = [r for r in atom_results if not r["dedicated"]]
    preserved = sum(1 for r in checkable if r["verdict"] in ("preserved", "equivalent"))
    rate = preserved / len(checkable) if checkable else 1.0
    passed = not any(v.severity == HARD for v in violations)

    return ValidationReport(
        violations=violations,
        atom_results=atom_results,
        preserved_rate=rate,
        passed=passed,
        stats={
            "atoms_locked": len(lock.atoms),
            "atoms_preserved": preserved,
            "claims_registered": len(lock.claims),
        },
    )
