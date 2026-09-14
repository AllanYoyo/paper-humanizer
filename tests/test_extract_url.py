from paper_humanizer.extract import extract_atoms


def test_url_with_zh_punctuation_stops_correctly():
    text = "数据见https://example.org/deploy-2024/data。"
    atoms = extract_atoms(text, text)
    urls = [a.canonical for a in atoms if a.kind == "url"]
    assert urls == ["URL(https://example.org/deploy-2024/data)"]


def test_url_trailing_ascii_punctuation_stripped():
    text = "see https://example.org/x, and text continues."
    atoms = extract_atoms(text, text)
    urls = [a.canonical for a in atoms if a.kind == "url"]
    assert urls == ["URL(https://example.org/x)"]


def test_url_change_is_a_different_atom():
    a = extract_atoms("见https://example.org/deploy-2024/data。", "见https://example.org/deploy-2024/data。")
    b = extract_atoms("见https://example.org/deploy-2025/data。", "见https://example.org/deploy-2025/data。")
    ua = {x.canonical for x in a if x.kind == "url"}
    ub = {x.canonical for x in b if x.kind == "url"}
    assert ua != ub
