"""Deterministic atom extraction.

Extracts the semantic atoms that Layer 2 can verify without an LLM: numbers,
percentages, amounts, dates/ranges, counts (sample sizes), p-values,
significance levels, coefficients, numbered/author-year citations, DOIs, URLs,
variables and glossary terms. Extraction order and span bookkeeping prevent
one pattern from stealing another's match (DOI before bare years, citations
before generic numbers, ...).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from paper_humanizer.normalize import (
    canonical_digits,
    parse_number,
    sentence_spans,
    trim_decimal,
    zh_numeral_to_int,
)

KIND_NUMBER = "number"
KIND_PERCENT = "percent"
KIND_AMOUNT = "amount"
KIND_DATE = "date"
KIND_RANGE = "range"
KIND_COUNT = "count"
KIND_PVALUE = "p_value"
KIND_SIG = "significance"
KIND_COEF = "coefficient"
KIND_CITE_NUM = "citation_numbered"
KIND_CITE_AY = "citation_ay"
KIND_DOI = "doi"
KIND_URL = "url"
KIND_TERM = "term"
KIND_VAR = "variable"
KIND_PHRASE = "phrase"

NUMERIC_KINDS = {
    KIND_NUMBER, KIND_PERCENT, KIND_AMOUNT, KIND_DATE, KIND_RANGE,
    KIND_COUNT, KIND_PVALUE, KIND_SIG, KIND_COEF,
}


@dataclass
class Atom:
    id: str = ""
    kind: str = ""
    surface: str = ""
    canonical: str = ""
    context: str = ""
    start: int = -1
    end: int = -1

    @property
    def key(self) -> tuple[str, str]:
        return (self.kind, self.canonical)


def _trim(value: Decimal) -> str:
    return trim_decimal(value)


def _canon_pct(value: Decimal) -> str:
    return f"PCT({_trim(value)})"


def _context_for(spans: list[tuple[int, int]], original: str, mid: int) -> str:
    for s, e in spans:
        if s <= mid < e:
            return original[s:e].strip()
    return ""


_RE_URL = re.compile(r"https?://[^\s<>（）()【】{}\"'，。；、！？]+")
_RE_DOI = re.compile(
    r"(?:doi\s*[:：]?\s*|https?://(?:dx\.)?doi\.org/)\s*(10\.\d{4,9}/[^\s，。；）)】]+)", re.I
)
_RE_CITE_NUM = re.compile(r"\[(\d{1,3}(?:\s*[,，]\s*\d{1,3})*)\]")
_RE_CITE_AY_CJK = re.compile(r"([\u4e00-\u9fff]{2,4}?)(?:等)?\s*[（(]\s*((?:19|20)\d{2})\s*[）)]")
_RE_CITE_AY_LAT = re.compile(r"([A-Z][A-Za-z&.\- ]{1,40}?)\s*[（(]\s*((?:19|20)\d{2})\s*[）)]")
_RE_CITE_AY_EN = re.compile(r"\(([A-Z][A-Za-z&.\- ]{0,40}?),\s*((?:19|20)\d{2})\)")

_RE_PCT_ZH = re.compile(r"百分之\s*([0-9]+(?:\.[0-9]+)?)")
_RE_PCT_SYM = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*[%％]")
_RE_PCT_DEC = re.compile(
    r"(?:占比|比例|份额|percent(?:age)?|proportion)\s*(?:为|是|of|:|：)?\s*(0\.[0-9]+)"
)

_RE_AMOUNT = re.compile(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(万|亿)?\s*(万元|亿元|美元|人民币|元)")

_RE_DATE_ISO = re.compile(r"(?<![0-9A-Za-z.])((?:19|20)\d{2})-([01][0-9])-([0-3][0-9])(?!\d)")
_RE_RANGE = re.compile(
    r"(?<![0-9A-Za-z.])((?:19|20)\d{2})\s*(?:[—–\-~～]|至|到)\s*((?:19|20)\d{2})(?!\d)(?:\s*年)?"
)
_RE_DATE_ZH = re.compile(r"((?:19|20)\d{2})\s*年(?:\s*([0-9]{1,2}|[一二三四五六七八九十]{1,3})\s*月)?")
_RE_DATE_EN = re.compile(
    r"(?<![A-Za-z])(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s+((?:19|20)\d{2})(?!\d)"
)
_RE_YEAR = re.compile(r"(?<![0-9A-Za-z.])((?:19|20)\d{2})(?![0-9])")

_RE_P = re.compile(r"(?<![A-Za-z0-9])[pP]\s*值?\s*([<＜>＞≤≥=＝])\s*(0?[0-9]*\.[0-9]+)")
_RE_P_EQ = re.compile(r"(?<![A-Za-z0-9])[pP]\s*值\s*(?:为|是)\s*(0?[0-9]*\.[0-9]+)")
_RE_SIG = re.compile(r"在\s*([0-9]+(?:\.[0-9]+)?)\s*%\s*的?水平(?:上)?\s*显著")

_RE_COEF_SYM = re.compile(r"[ββ]\s*[=＝]\s*(-?[0-9]+(?:\.[0-9]+)?)")
_RE_COEF_CTX = re.compile(r"系数(?:为|是)?\s*(-?[0-9]+(?:\.[0-9]+)?)")

_RE_PHRASE = re.compile(r"(近|过去)\s*([0-9一二两三四五六七八九十]+)\s*年")

_RE_COUNT_N = re.compile(r"(?<![A-Za-z0-9])[nN]\s*[=＝]\s*([0-9][0-9,]*)")
_RE_COUNT_UNIT = re.compile(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(家|名|人|份|例|篇|条|项|种)")
_RE_COUNT_EN = re.compile(r"([0-9][0-9,]*)\s+(firms|participants|respondents|samples|observations|countries)", re.I)

_RE_NUM = re.compile(r"(?<![0-9A-Za-z.])(-?[0-9]+(?:\.[0-9]+)?)(?![0-9A-Za-z])")
_RE_VAR = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2,8}(?![A-Za-z0-9])")
_RE_QUOTED = re.compile("[\"“]([^\"”]{2,24})[\"”]")

_MONTH = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}
_P_OP = {"<": "lt", "＜": "lt", "<=": "le", "≤": "le", ">": "gt", "＞": "gt", "≥": "ge", "=": "eq", "＝": "eq"}
_AMOUNT_MULT = {"万": Decimal(10_000), "亿": Decimal(100_000_000)}
_AMOUNT_CUR = {"万元": "CNY", "亿元": "CNY", "人民币": "CNY", "美元": "USD", "元": "CNY"}


def _overlaps(taken: list[tuple[int, int]], start: int, end: int) -> bool:
    return any(start < e and s < end for s, e in taken)


def extract_atoms(masked: str, original: str, glossary: Sequence[str] = ()) -> list[Atom]:
    """Extract atoms from ``masked`` text (frozen regions blanked, same offsets as original)."""
    taken: list[tuple[int, int]] = []
    atoms: list[Atom] = []
    spans = sentence_spans(original)

    def add(kind: str, surface: str, canonical: str, start: int, end: int) -> bool:
        if end <= start or _overlaps(taken, start, end):
            return False
        taken.append((start, end))
        atoms.append(Atom(kind=kind, surface=surface, canonical=canonical,
                          context=_context_for(spans, original, (start + end) // 2),
                          start=start, end=end))
        return True

    for m in _RE_URL.finditer(masked):
        surface = m.group(0).rstrip(".,;:、，。；")
        add(KIND_URL, surface, f"URL({surface})", m.start(), m.start() + len(surface))
    for m in _RE_DOI.finditer(masked):
        doi = m.group(1).rstrip(".,;、，。；)")
        add(KIND_DOI, doi, f"DOI({doi.lower()})", m.start(1), m.end(1))
    for m in _RE_CITE_NUM.finditer(masked):
        nums = [int(x) for x in re.split(r"[,，]", m.group(1))]
        add(KIND_CITE_NUM, m.group(0),
            "CITES(" + ",".join(str(n) for n in sorted(nums)) + ")", m.start(), m.end())
    for regex in (_RE_CITE_AY_CJK, _RE_CITE_AY_LAT, _RE_CITE_AY_EN):
        for m in regex.finditer(masked):
            name = re.sub(r"\s+", "", m.group(1)).lower()
            add(KIND_CITE_AY, m.group(0), f"CITE_AY({name},{m.group(2)})", m.start(), m.end())

    # SIG before PCT: "在1%水平上显著" must not be stolen as a bare percentage.
    for m in _RE_SIG.finditer(masked):
        level = parse_number(m.group(1)) / Decimal(100)
        add(KIND_SIG, m.group(0), f"SIG({_trim(level)})", m.start(), m.end())

    for m in _RE_PCT_ZH.finditer(masked):
        add(KIND_PERCENT, m.group(0), _canon_pct(parse_number(m.group(1))), m.start(), m.end())
    for m in _RE_PCT_SYM.finditer(masked):
        add(KIND_PERCENT, m.group(0), _canon_pct(parse_number(m.group(1))), m.start(), m.end())
    for m in _RE_PCT_DEC.finditer(masked):
        add(KIND_PERCENT, m.group(0), _canon_pct(parse_number(m.group(1)) * 100), m.start(), m.end())

    for m in _RE_AMOUNT.finditer(masked):
        value = parse_number(m.group(1))
        if m.group(2):
            value = value * _AMOUNT_MULT[m.group(2)]
        add(KIND_AMOUNT, m.group(0),
            f"{_AMOUNT_CUR[m.group(3)]}({_trim(value)})", m.start(), m.end())

    for m in _RE_DATE_ISO.finditer(masked):
        add(KIND_DATE, m.group(0), f"DATE({m.group(1)}-{m.group(2)}-{m.group(3)})", m.start(), m.end())
    for m in _RE_RANGE.finditer(masked):
        add(KIND_RANGE, m.group(0), f"RANGE({m.group(1)},{m.group(2)})", m.start(), m.end())
    for m in _RE_DATE_ZH.finditer(masked):
        month = m.group(2)
        canonical = f"DATE({m.group(1)})" if not month else f"DATE({m.group(1)}-{int(zh_numeral_to_int(month) or 0):02d})"
        add(KIND_DATE, m.group(0), canonical, m.start(), m.end())
    for m in _RE_DATE_EN.finditer(masked):
        add(KIND_DATE, m.group(0), f"DATE({m.group(2)}-{_MONTH[m.group(1)]:02d})", m.start(), m.end())

    for m in _RE_P.finditer(masked):
        op = _P_OP[canonical_digits(m.group(1))]
        add(KIND_PVALUE, m.group(0), f"P({op},{_trim(parse_number(m.group(2)))})", m.start(), m.end())
    for m in _RE_P_EQ.finditer(masked):
        add(KIND_PVALUE, m.group(0), f"P(eq,{_trim(parse_number(m.group(1)))})", m.start(), m.end())

    for m in _RE_COEF_SYM.finditer(masked):
        add(KIND_COEF, m.group(0), f"COEF({_trim(parse_number(m.group(1)))})", m.start(), m.end())
    for m in _RE_COEF_CTX.finditer(masked):
        add(KIND_COEF, m.group(0), f"COEF({_trim(parse_number(m.group(1)))})", m.start(), m.end())

    for m in _RE_PHRASE.finditer(masked):
        num = zh_numeral_to_int(m.group(2))
        if num is None:
            num = int(canonical_digits(m.group(2)))
        add(KIND_PHRASE, m.group(0), f"PHRASE({m.group(1)}{num}年)", m.start(), m.end())

    for m in _RE_COUNT_N.finditer(masked):
        add(KIND_COUNT, m.group(0), f"COUNT({_trim(parse_number(m.group(1)))})", m.start(), m.end())
    for m in _RE_COUNT_UNIT.finditer(masked):
        add(KIND_COUNT, m.group(0), f"COUNT({_trim(parse_number(m.group(1)))})", m.start(), m.end())
    for m in _RE_COUNT_EN.finditer(masked):
        add(KIND_COUNT, m.group(0), f"COUNT({_trim(parse_number(m.group(1)))})", m.start(), m.end())

    for m in _RE_YEAR.finditer(masked):
        add(KIND_DATE, m.group(0), f"DATE({m.group(1)})", m.start(), m.end())
    for m in _RE_NUM.finditer(masked):
        add(KIND_NUMBER, m.group(0), f"NUM({_trim(parse_number(m.group(1)))})", m.start(), m.end())

    var_counts: dict[str, int] = {}
    for m in _RE_VAR.finditer(masked):
        var_counts[m.group(0)] = var_counts.get(m.group(0), 0) + 1
    for var, count in var_counts.items():
        if count >= 2:
            m = re.search(re.escape(var), masked)
            add(KIND_VAR, var, f"VAR({var})", m.start(), m.end())

    for m in _RE_QUOTED.finditer(masked):
        add(KIND_TERM, m.group(0), f"TERM({m.group(1)})", m.start(), m.end())
    for term in glossary:
        term = term.strip()
        if not term:
            continue
        m = re.search(re.escape(term), masked)
        if m:
            add(KIND_TERM, term, f"TERM({term})", m.start(), m.end())

    atoms.sort(key=lambda a: (a.start if a.start >= 0 else 10**9, a.kind))
    seen: set[tuple[str, str]] = set()
    unique: list[Atom] = []
    for atom in atoms:
        if atom.key in seen:
            continue
        seen.add(atom.key)
        unique.append(atom)
    return unique
