from paper_humanizer.extract import extract_atoms


def kinds(atoms, kind):
    return [a.canonical for a in atoms if a.kind == kind]


def test_numbers_amounts_coefficients_pvalues_counts():
    text = ("2020—2024年共调查了327家企业，其中183家完成了两期追踪调查。"
            "数字化投入均值为286.4万元。回归系数为β=0.42（p<0.01），企业年龄的系数为-0.02。"
            "子样本（n=152）。均值为56.8。占比为34.5%。该系数在1%水平上显著。")
    atoms = extract_atoms(text, text)
    assert "RANGE(2020,2024)" in kinds(atoms, "range")
    assert kinds(atoms, "count") == ["COUNT(327)", "COUNT(183)", "COUNT(152)"]
    assert "CNY(2864000)" in kinds(atoms, "amount")
    assert "COEF(0.42)" in kinds(atoms, "coefficient")
    assert "COEF(-0.02)" in kinds(atoms, "coefficient")
    assert "P(lt,0.01)" in kinds(atoms, "p_value")
    assert "NUM(56.8)" in kinds(atoms, "number")
    assert kinds(atoms, "percent") == ["PCT(34.5)"]
    assert "SIG(0.01)" in kinds(atoms, "significance")


def test_amount_equivalence():
    text_a = "投入为286.4万元。"
    text_b = "投入为2,864,000元。"
    a = extract_atoms(text_a, text_a)
    b = extract_atoms(text_b, text_b)
    assert kinds(a, "amount") == kinds(b, "amount") == ["CNY(2864000)"]


def test_negative_coefficient_sign_is_part_of_atom():
    text = "系数为-0.02，另一系数为0.02。"
    atoms = extract_atoms(text, text)
    assert sorted(kinds(atoms, "coefficient")) == ["COEF(-0.02)", "COEF(0.02)"]


def test_p_value_thresholds_differ():
    text = "p<0.01 与 p<0.05 与 P=0.031。"
    atoms = extract_atoms(text, text)
    assert sorted(kinds(atoms, "p_value")) == ["P(eq,0.031)", "P(lt,0.01)", "P(lt,0.05)"]
