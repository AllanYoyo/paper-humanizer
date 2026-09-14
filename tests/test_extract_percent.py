from paper_humanizer.extract import extract_atoms


def kinds(atoms, kind):
    return [a.canonical for a in atoms if a.kind == kind]


def test_percent_symbol_and_zh_forms_equivalent():
    a = extract_atoms("比例为34.5%。", "比例为34.5%。")
    b = extract_atoms("占比为百分之34.5。", "占比为百分之34.5。")
    c = extract_atoms("占比为0.345。", "占比为0.345。")
    assert kinds(a, "percent") == ["PCT(34.5)"]
    assert kinds(b, "percent") == ["PCT(34.5)"]
    assert kinds(c, "percent") == ["PCT(34.5)"]


def test_percentage_point_is_not_a_percent():
    text = "提高了34.5个百分点。"
    atoms = extract_atoms(text, text)
    assert kinds(atoms, "percent") == []
    assert "NUM(34.5)" in kinds(atoms, "number")


def test_bare_decimal_without_keyword_is_not_percent():
    text = "均值为0.345。"
    atoms = extract_atoms(text, text)
    assert kinds(atoms, "percent") == []
    assert "NUM(0.345)" in kinds(atoms, "number")


def test_significance_level_not_stolen_as_percent():
    text = "结果在1%水平上显著，效应为34.5%。"
    atoms = extract_atoms(text, text)
    assert kinds(atoms, "percent") == ["PCT(34.5)"]
    assert "SIG(0.01)" in kinds(atoms, "significance")
