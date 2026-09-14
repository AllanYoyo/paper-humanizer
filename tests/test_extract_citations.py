from paper_humanizer.extract import extract_atoms
from paper_humanizer.validate import _flatten_cited_numbers


def kinds(atoms, kind):
    return [a.canonical for a in atoms if a.kind == kind]


def test_numbered_citations_multiset():
    text = "相关研究见[12]、[1,2]与[3][4]。"
    atoms = extract_atoms(text, text)
    assert sorted(_flatten_cited_numbers(atoms)) == [1, 2, 3, 4, 12]


def test_author_year_three_forms():
    text = "(Chen & Zhao, 2023) 提出了框架；张三等（2021）扩展了它；Chen & Zhao（2023）再次验证。"
    atoms = extract_atoms(text, text)
    assert "CITE_AY(chen&zhao,2023)" in kinds(atoms, "citation_ay")
    assert "CITE_AY(张三,2021)" in kinds(atoms, "citation_ay")


def test_doi_direct_and_url_form():
    text = "材料见DOI: 10.1234/abc.2023.001；镜像见 https://doi.org/10.5555/xyz。"
    atoms = extract_atoms(text, text)
    assert "DOI(10.1234/abc.2023.001)" in kinds(atoms, "doi")
    # doi.org links are captured as URLs (dedup: DOI pass is blocked by the URL span)
    assert "URL(https://doi.org/10.5555/xyz)" in kinds(atoms, "url")


def test_citation_renumber_detected_as_changed_multiset():
    a = extract_atoms("见[12]。", "见[12]。")
    b = extract_atoms("见[13]。", "见[13]。")
    assert _flatten_cited_numbers(a) == [12]
    assert _flatten_cited_numbers(b) == [13]
