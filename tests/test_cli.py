"""CLI smoke tests (no network, no provider)."""
from paper_humanizer.cli import main


def write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_cli_diagnose_exit_zero(tmp_path, capsys, sample_zh):
    p = write(tmp_path, "paper.md", sample_zh)
    assert main(["diagnose", str(p)]) == 0
    out = capsys.readouterr().out
    assert "ai-style level" in out


def test_cli_validate_identity_passes(tmp_path, capsys, sample_zh):
    a = write(tmp_path, "a.md", sample_zh)
    b = write(tmp_path, "b.md", sample_zh)
    assert main(["validate", str(a), str(b)]) == 0
    assert "PASS" in capsys.readouterr().out


def test_cli_validate_tampered_number_fails(tmp_path, capsys, sample_zh):
    a = write(tmp_path, "a.md", sample_zh)
    b = write(tmp_path, "b.md", sample_zh.replace("327家", "237家"))
    assert main(["validate", str(a), str(b)]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_cli_rewrite_without_provider_errors(tmp_path, capsys, sample_zh):
    p = write(tmp_path, "paper.md", sample_zh)
    assert main(["rewrite", str(p)]) == 2
    assert "PAPER_HUMANIZER" in capsys.readouterr().err


def test_cli_review_without_revision_reviews_input(tmp_path, capsys, sample_zh):
    p = write(tmp_path, "paper.md", sample_zh)
    assert main(["review", str(p)]) == 0
    assert "document review" in capsys.readouterr().out


def test_cli_review_with_revision_checks_preservation(tmp_path, capsys, sample_zh):
    write(tmp_path, "paper.md", sample_zh)
    rev = write(tmp_path, "paper.humanized.md", sample_zh.replace("327家", "237家"))
    assert rev.is_file()
    assert main(["review", str(tmp_path / "paper.md")]) == 1
    assert "FAIL" in capsys.readouterr().out
