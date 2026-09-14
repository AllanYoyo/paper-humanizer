"""Text normalization.

Two strictly separated levels:
- document level (``normalize_document``): lossless cleanup, never changes characters of record;
- value level (``canonical_digits`` / ``parse_number`` / zh numerals): canonical forms used
  ONLY for comparison, never written back into user text.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

_ZH_DIGIT = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_ZH_UNIT = {"十": 10, "百": 100, "千": 1000}
_ZH_BIG = {"万": 10_000, "亿": 100_000_000}

# Used only inside canonicalization, never on the document itself.
_FULLWIDTH = str.maketrans({
    "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
    "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
    "（": "(", "）": ")", "＜": "<", "＞": ">", "＝": "=",
    "％": "%", "：": ":", "，": ",",
})

_ZH_END = "。！？；!?;"


def zh_numeral_to_int(text: str) -> int | None:
    """Convert a pure Chinese numeral string (三万六千, 一百零三, 十五) to int; None if not pure."""
    total = section = current = 0
    seen = False
    for ch in text:
        if ch in _ZH_DIGIT:
            current = _ZH_DIGIT[ch]
            seen = True
        elif ch in _ZH_UNIT:
            section += (current or 1) * _ZH_UNIT[ch]
            current = 0
            seen = True
        elif ch in _ZH_BIG:
            section = (section + current) * _ZH_BIG[ch]
            total += section
            section = current = 0
            seen = True
        elif ch == "零":
            seen = True
        else:
            return None
    return total + section + current if seen else None


def normalize_document(text: str) -> str:
    """Lossless cleanup: NFC, unified newlines, trailing whitespace, blank-line collapse."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip("\n") + ("\n" if text else "")


def canonical_digits(s: str) -> str:
    return s.translate(_FULLWIDTH)


def parse_number(s: str) -> Decimal:
    """Parse '2,864,000' / '２８６.４' / '34.5' into Decimal."""
    return Decimal(canonical_digits(s).replace(",", "").strip())


def trim_decimal(d: Decimal) -> str:
    d = d.normalize()
    if d == d.to_integral_value():
        return str(int(d))
    return format(d, "f")


def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", "", s)


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """Heuristic sentence spans for mixed zh/en text (used for context quotes)."""
    spans: list[tuple[int, int]] = []
    start = 0
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch in _ZH_END:
            spans.append((start, i + 1))
            start = i + 1
        elif ch == "." and i + 1 < n and text[i + 1] in " \n" and i > start and text[i - 1].isalpha():
            spans.append((start, i + 1))
            start = i + 1
        elif ch == "\n":
            spans.append((start, i + 1))
            start = i + 1
        i += 1
    if start < n:
        spans.append((start, n))
    return [(s, e) for s, e in spans if text[s:e].strip()]
