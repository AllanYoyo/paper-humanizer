from decimal import Decimal

from paper_humanizer.normalize import (
    canonical_digits,
    normalize_document,
    parse_number,
    sentence_spans,
    trim_decimal,
    zh_numeral_to_int,
)


def test_zh_numerals():
    assert zh_numeral_to_int("三百二十") == 320
    assert zh_numeral_to_int("十五") == 15
    assert zh_numeral_to_int("一百零三") == 103
    assert zh_numeral_to_int("两千五百") == 2500
    assert zh_numeral_to_int("三万六千") == 36000
    assert zh_numeral_to_int("两") == 2
    assert zh_numeral_to_int("十") == 10
    assert zh_numeral_to_int("abc") is None


def test_parse_number_canonical():
    assert parse_number("2,864,000") == Decimal("2864000")
    assert parse_number("２８６.４") == Decimal("286.4")
    assert trim_decimal(Decimal("0.345") * 100) == "34.5"
    assert trim_decimal(parse_number("286.4") * 10000) == "2864000"
    assert canonical_digits("（p＜0.01）") == "(p<0.01)"


def test_normalize_document_lossless():
    raw = "第一段。\r\n\r\n\r\n\r\n第二段。  \n"
    out = normalize_document(raw)
    assert "\r" not in out
    assert "\n\n\n" not in out
    assert "第一段。" in out and "第二段。" in out


def test_sentence_spans_mixed():
    text = "第一句。第二句！This is English. 第三句。"
    spans = sentence_spans(text)
    assert len(spans) >= 4
