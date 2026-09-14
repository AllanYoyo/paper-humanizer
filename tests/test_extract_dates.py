from paper_humanizer.extract import extract_atoms


def kinds(atoms, kind):
    return [a.canonical for a in atoms if a.kind == kind]


def test_year_range_variants():
    text = "研究期为2020—2024年；其后2019至2023的样本；还有2018-2022。"
    atoms = extract_atoms(text, text)
    assert "RANGE(2020,2024)" in kinds(atoms, "range")
    assert "RANGE(2019,2023)" in kinds(atoms, "range")
    assert "RANGE(2018,2022)" in kinds(atoms, "range")


def test_date_forms():
    text = "调研始于2020年3月；2020年发布；March 2020 updated；2020-03-01 snapshot。"
    atoms = extract_atoms(text, text)
    assert "DATE(2020-03)" in kinds(atoms, "date")
    assert "DATE(2020-03-01)" in kinds(atoms, "date")
    assert "DATE(2020)" in kinds(atoms, "date")


def test_natural_language_ranges_are_frozen_phrases():
    text = "近三年，样本扩展；过去五年间，数据翻倍。"
    atoms = extract_atoms(text, text)
    assert "PHRASE(近3年)" in kinds(atoms, "phrase")
    assert "PHRASE(过去5年)" in kinds(atoms, "phrase")


def test_range_not_split_into_dates():
    text = "2020—2024年共调查了327家企业。"
    atoms = extract_atoms(text, text)
    assert "RANGE(2020,2024)" in kinds(atoms, "range")
    assert kinds(atoms, "date") == []
