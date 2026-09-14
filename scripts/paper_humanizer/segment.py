"""Document segmentation: sections, blocks, and frozen regions.

Frozen regions (markdown tables, fenced code, the references section, heading
lines) are never rewritten; they are masked before atom extraction and their
content is fingerprint-compared after rewriting.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_REFS_TITLE = re.compile(r"^(references|bibliography|参考文献|参考文献)$", re.I)
_TABLE_LINE = re.compile(r"^\s*\|")
_SEP_CELL = re.compile(r":?-{2,}:?")


@dataclass
class Block:
    kind: str  # "prose" | "frozen"
    text: str
    start: int
    end: int
    index: int = -1


@dataclass
class Section:
    id: str
    title: str
    level: int
    heading_line: str
    start: int
    end: int
    blocks: list[Block] = field(default_factory=list)
    section_type: str = "general"
    frozen: bool = False


@dataclass
class SegmentResult:
    sections: list[Section]
    headings: list[str]
    tables: list[list[list[str]]]
    codes: list[str]
    frozen: list[tuple[int, int, str]]


def _iter_lines(text: str):
    pos = 0
    for line in text.split("\n"):
        yield pos, pos + len(line), line
        pos += len(line) + 1


def _heading_spans(text: str) -> list[tuple[int, int, int, str]]:
    out = []
    for s, e, line in _iter_lines(text):
        m = _HEADING.match(line)
        if m:
            out.append((s, e, len(m.group(1)), m.group(2).strip()))
    return out


def _fence_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    open_start: int | None = None
    for s, e, line in _iter_lines(text):
        if line.lstrip().startswith("```"):
            if open_start is None:
                open_start = s
            else:
                spans.append((open_start, e))
                open_start = None
    if open_start is not None:
        spans.append((open_start, len(text)))
    return spans


def _table_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cur: tuple[int, int] | None = None
    for s, e, line in _iter_lines(text):
        if _TABLE_LINE.match(line):
            cur = (cur[0] if cur else s, e)
        else:
            if cur:
                spans.append(cur)
                cur = None
    if cur:
        spans.append(cur)
    return spans


def _refs_span(text: str) -> tuple[int, int] | None:
    heads = _heading_spans(text)
    for i, (s, _e, _lvl, title) in enumerate(heads):
        if _REFS_TITLE.fullmatch(title):
            end = heads[i + 1][0] if i + 1 < len(heads) else len(text)
            return (s, end)
    return None


def frozen_ranges(text: str) -> list[tuple[int, int, str]]:
    out = [(s, e, "code") for s, e in _fence_spans(text)]
    out += [(s, e, "table") for s, e in _table_spans(text)]
    refs = _refs_span(text)
    if refs:
        out.append((refs[0], refs[1], "references"))
    return out


def _table_rows(block_text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in block_text.split("\n"):
        if not line.strip():
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and all(_SEP_CELL.fullmatch(c) for c in cells if c):
            continue  # separator row |---|---|
        if any(c for c in cells):
            rows.append(cells)
    return rows


def heading_inventory(text: str) -> list[str]:
    return [f"{'#' * lvl} {title}" for _s, _e, lvl, title in _heading_spans(text)]


def frozen_inventory(text: str) -> dict:
    ranges = frozen_ranges(text)
    return {
        "tables": [_table_rows(text[s:e]) for s, e, kind in ranges if kind == "table"],
        "codes": [text[s:e] for s, e, kind in ranges if kind == "code"],
    }


def mask_for_extraction(text: str, seg: "SegmentResult | None" = None) -> str:
    ranges = list(seg.frozen) if seg is not None else frozen_ranges(text)
    ranges += [(s, e, "heading") for s, e, _lvl, _t in _heading_spans(text)]
    chars = list(text)
    for s, e, _kind in ranges:
        for i in range(s, min(e, len(chars))):
            if chars[i] != "\n":
                chars[i] = " "
    return "".join(chars)


_CLASSIFY = [
    ("abstract", ("摘要", "abstract")),
    ("intro", ("引言", "绪论", "introduction", "研究背景")),
    ("related", ("文献", "综述", "related", "literature")),
    ("methods", ("方法", "数据", "模型设定", "method", "data", "materials")),
    ("results", ("结果", "实证", "findings", "results", "回归")),
    ("discussion", ("讨论", "discussion")),
    ("conclusion", ("结论", "conclusion", "总结")),
]


def classify_section(title: str) -> str:
    t = title.strip().lower()
    for name, keywords in _CLASSIFY:
        if any(k in t for k in keywords):
            return name
    return "general"


def _make_section(text: str, title: str, level: int, heading_line: str,
                  content_start: int, content_end: int, franges, sec_idx: int) -> Section:
    sec = Section(id=f"sec-{sec_idx + 1:03d}", title=title, level=level,
                  heading_line=heading_line, start=content_start, end=content_end)
    sec.section_type = classify_section(title)
    inner = sorted((s, e, k) for s, e, k in franges if content_start <= s and e <= content_end)
    pos = content_start
    for s, e, _k in inner:
        if s > pos:
            sec.blocks.append(Block("prose", text[pos:s], pos, s))
        sec.blocks.append(Block("frozen", text[s:e], s, e))
        pos = e
    if pos < content_end:
        sec.blocks.append(Block("prose", text[pos:content_end], pos, content_end))
    return sec


def segment_document(text: str) -> SegmentResult:
    heads = _heading_spans(text)
    refs = _refs_span(text)
    fr = frozen_ranges(text)
    sections: list[Section] = []
    idx = 0

    if not heads:
        preamble = _make_section(text, "", 0, "", 0, len(text), fr, 0)
        for b in preamble.blocks:
            b.index = idx
            idx += 1
        sections.append(preamble)
    else:
        if heads[0][0] > 0:
            preamble = _make_section(text, "", 0, "", 0, heads[0][0], fr, 0)
            for b in preamble.blocks:
                b.index = idx
                idx += 1
            sections.append(preamble)
        for i, (s, _e, lvl, title) in enumerate(heads):
            end = heads[i + 1][0] if i + 1 < len(heads) else len(text)
            heading_line = text[s:_e]
            sec = _make_section(text, title, lvl, heading_line, _e, end, fr, len(sections))
            if refs and refs[0] <= s < refs[1]:
                sec.frozen = True
            for b in sec.blocks:
                b.index = idx
                idx += 1
            sections.append(sec)

    tables = [_table_rows(text[s:e]) for s, e, kind in fr if kind == "table"]
    codes = [text[s:e] for s, e, kind in fr if kind == "code"]
    return SegmentResult(
        sections=sections,
        headings=heading_inventory(text),
        tables=tables,
        codes=codes,
        frozen=fr,
    )


def assemble(seg: SegmentResult, replacements: dict[int, str]) -> str:
    """Rebuild the document; identity when ``replacements`` is empty."""
    parts: list[str] = []
    for sec in seg.sections:
        if sec.heading_line:
            parts.append(sec.heading_line)
        for b in sec.blocks:
            if b.kind == "prose" and b.index in replacements:
                parts.append(replacements[b.index])
            else:
                parts.append(b.text)
    return "".join(parts)
