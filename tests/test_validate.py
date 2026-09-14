"""Deterministic validation: hard-fail rules, equivalence channels, structure."""
import pytest

from paper_humanizer.lock import build_lock
from paper_humanizer.validate import validate_document


def rules(report):
    return {v.rule for v in report.violations}


def test_identity_passes(sample_zh, sample_lock):
    report = validate_document(sample_lock, sample_zh)
    assert report.passed
    assert report.preserved_rate == 1.0
    assert rules(report) == set()


def test_sentence_reorder_keeps_semantic_content(sample_zh, sample_lock):
    a = "首先，从表1可以看出，数字化转型指数DTI的均值为56.8，供应链韧性SCR的平均得分为3.42。其次，企业规模的均值为5.87。"
    b = "其次，企业规模的均值为5.87。首先，从表1可以看出，数字化转型指数DTI的均值为56.8，供应链韧性SCR的平均得分为3.42。"
    reordered = sample_zh.replace(a, b)
    assert reordered != sample_zh
    report = validate_document(sample_lock, reordered)
    assert report.passed


def test_number_change_is_hard_fail(sample_zh, sample_lock):
    report = validate_document(sample_lock, sample_zh.replace("327家", "237家"))
    assert not report.passed
    assert "atom_changed" in rules(report)


def test_citation_lost_is_hard_fail(sample_zh, sample_lock):
    revised = sample_zh.replace("（2023）[12]基于", "（2023）基于")
    report = validate_document(sample_lock, revised)
    assert not report.passed
    assert "citation_lost" in rules(report)


def test_url_change_is_hard_fail(sample_zh, sample_lock):
    report = validate_document(sample_lock, sample_zh.replace("deploy-2024", "deploy-2025"))
    assert not report.passed
    assert "doi_url_changed" in rules(report)


def test_percent_decimal_equivalence_passes(sample_zh, sample_lock):
    revised = sample_zh.replace("比例为34.5%", "比例为0.345")
    report = validate_document(sample_lock, revised)
    assert report.passed
    assert any(r["verdict"] == "equivalent" for r in report.atom_results)


def test_amount_unit_equivalence_passes(sample_zh, sample_lock):
    report = validate_document(sample_lock, sample_zh.replace("286.4万元", "2,864,000元"))
    assert report.passed


def test_significance_pvalue_bridge(sample_zh=None):
    from paper_humanizer.normalize import normalize_document

    orig = normalize_document("该结果在1%水平上显著。\n")
    rev = normalize_document("该结果在p<0.01的水平上显著。\n")
    lock = build_lock(orig)
    report = validate_document(lock, rev)
    assert report.passed


def test_sample_count_change_is_hard_fail(sample_zh, sample_lock):
    report = validate_document(sample_lock, sample_zh.replace("n=152", "n=125"))
    assert not report.passed
    assert "atom_changed" in rules(report)


def test_glossary_term_drift_is_hard_fail(sample_zh, sample_lock):
    revised = sample_zh.replace("供应网络多元化", "供应网络分散化")
    report = validate_document(sample_lock, revised)
    assert not report.passed
    assert "term_drift" in rules(report)


def test_added_number_is_new_data(sample_zh, sample_lock):
    revised = sample_zh.replace(
        "数字化投入均值为286.4万元。",
        "数字化投入均值为286.4万元，问卷覆盖率达89.2%。")
    report = validate_document(sample_lock, revised)
    assert not report.passed
    assert "new_data_atom" in rules(report)


def test_pvalue_threshold_change(sample_zh, sample_lock):
    report = validate_document(sample_lock, sample_zh.replace("（p<0.01）", "（p<0.05）"))
    assert not report.passed
    # the old threshold disappears; whether it pairs with the new one depends on multiset order
    assert rules(report) & {"atom_changed", "atom_missing"}


def test_table_cell_modification_is_frozen_region_fail(sample_zh, sample_lock):
    report = validate_document(sample_lock, sample_zh.replace("0.42***", "0.43***"))
    assert not report.passed
    assert "frozen_region_modified" in rules(report)


def test_heading_removal_breaks_structure(sample_zh, sample_lock):
    revised = sample_zh.replace("### 4.2 基准回归与稳健性检验\n", "")
    assert revised != sample_zh
    report = validate_document(sample_lock, revised)
    assert not report.passed
    assert "structure_broken" in rules(report)
