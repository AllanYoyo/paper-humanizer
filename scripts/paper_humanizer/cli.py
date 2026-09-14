"""Command-line interface.

    paper-humanizer diagnose  input.md
    paper-humanizer rewrite   input.md
    paper-humanizer validate  original.md revised.md
    paper-humanizer review    input.md

Exit codes: 0 = pass, 1 = validation failures (report produced), 2 = error.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paper_humanizer.errors import PaperHumanizerError
from paper_humanizer.lock import build_lock, load_glossary_for
from paper_humanizer.normalize import normalize_document
from paper_humanizer.provider import provider_from_env
from paper_humanizer.validate import validate_document


def _cmd_diagnose(input_path: Path) -> int:
    from paper_humanizer.diagnose import diagnose_document, render_diagnosis

    text = input_path.read_text(encoding="utf-8")
    result = diagnose_document(text, provider=provider_from_env())
    print(render_diagnosis(result))
    return 0


def _cmd_rewrite(input_path: Path) -> int:
    from paper_humanizer.pipeline import run_rewrite

    result = run_rewrite(input_path, provider_from_env())
    print(f"status: {result.status}")
    print(f"repair loops used: {result.loops_used}")
    print(f"output: {result.run_dir / 'final.md'}")
    print(f"report: {result.run_dir / 'report.md'}")
    if result.status == "reverted":
        print("hard violations persisted after repair; the ORIGINAL text was kept:")
        for v in result.validation.hard_violations:
            print(f"  - [{v.rule}] {v.detail}")
        for item in (result.review or {}).get("hard_violations", []):
            print(f"  - [{item['rule']}] {item['detail']}")
        return 1
    return 0


def _cmd_validate(original_path: Path, revised_path: Path) -> int:
    original = normalize_document(original_path.read_text(encoding="utf-8"))
    lock = build_lock(original, source=str(original_path),
                      glossary=load_glossary_for(original_path))
    report = validate_document(lock, revised_path.read_text(encoding="utf-8"))
    print(f"atoms locked: {report.stats['atoms_locked']}  "
          f"preserved rate: {report.preserved_rate:.2%}")
    if report.violations:
        print("violations:")
        for v in report.violations:
            print(f"  - [{v.severity}] {v.rule}: {v.detail}")
    else:
        print("violations: (none)")
    print("PASS" if report.passed else "FAIL")
    return 0 if report.passed else 1


def _cmd_review(input_path: Path) -> int:
    from paper_humanizer.diagnose import diagnose_document, render_diagnosis

    text = normalize_document(input_path.read_text(encoding="utf-8"))
    provider = provider_from_env()
    humanized = input_path.with_name(input_path.stem + ".humanized.md")

    if humanized.is_file():
        from paper_humanizer.pipeline import build_enriched_lock
        from paper_humanizer.prompts_loader import ask_json
        from paper_humanizer.review import review_revision

        revised = humanized.read_text(encoding="utf-8")
        warnings: list[str] = []
        lock = build_enriched_lock(text, input_path, provider, warnings)
        report = validate_document(lock, revised)
        print(f"== preservation review: {input_path.name} vs {humanized.name} ==")
        print(f"atoms locked: {report.stats['atoms_locked']}  "
              f"preserved rate: {report.preserved_rate:.2%}")
        for v in report.violations:
            print(f"  - [{v.severity}] {v.rule}: {v.detail}")
        hard = report.hard_violations
        if provider.available:
            try:
                review_data = review_revision(provider, text, revised, lock)
                for item in review_data["hard_violations"]:
                    print(f"  - [hard] {item['rule']}: {item['detail']}")
                naturalness = review_data.get("naturalness") or {}
                print(f"naturalness (judge): {naturalness.get('score', 'n/a')}/5  "
                      f"decision: {review_data.get('decision')}")
                hard = hard + review_data["hard_violations"]
            except Exception as exc:  # noqa: BLE001 — review is best-effort
                print(f"note: LLM review unavailable: {exc}")
        print("PASS" if not hard else "FAIL")
        return 0 if not hard else 1

    result = diagnose_document(text, provider=provider)
    print(f"== document review: {input_path.name} "
          f"(no {humanized.name} found; reviewing the input itself) ==")
    print(render_diagnosis(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="paper-humanizer",
        description="Naturalize academic papers with strict semantic preservation.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_diag = sub.add_parser("diagnose", help="deterministic (+optional LLM) AI-style diagnosis")
    p_diag.add_argument("input")
    p_rw = sub.add_parser("rewrite", help="full pipeline: diagnose → lock → rewrite → validate → review → repair")
    p_rw.add_argument("input")
    p_val = sub.add_parser("validate", help="deterministic semantic-lock validation")
    p_val.add_argument("original")
    p_val.add_argument("revised")
    p_rev = sub.add_parser("review", help="review the document, or its <stem>.humanized.md revision if present")
    p_rev.add_argument("input")
    args = parser.parse_args(argv)

    try:
        if args.command == "diagnose":
            return _cmd_diagnose(Path(args.input))
        if args.command == "rewrite":
            return _cmd_rewrite(Path(args.input))
        if args.command == "validate":
            return _cmd_validate(Path(args.original), Path(args.revised))
        if args.command == "review":
            return _cmd_review(Path(args.input))
    except PaperHumanizerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
