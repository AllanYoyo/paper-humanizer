"""Resolve bundled asset locations.

Works in three layouts: the repo/ skill checkout (SKILL.md + references/ + prompts/),
a pip-installed package (assets resolved via PAPER_HUMANIZER_HOME), or any install
tree that keeps the skill directory structure intact.
"""
from __future__ import annotations

import os
from pathlib import Path

from paper_humanizer.errors import ConfigError

ENV_HOME = "PAPER_HUMANIZER_HOME"


def find_project_root(start: Path | None = None) -> Path:
    env = os.environ.get(ENV_HOME)
    if env:
        p = Path(env).expanduser().resolve()
        if p.is_dir():
            return p
    here = (start or Path(__file__).resolve()).parent
    for cand in (here, *here.parents):
        if (cand / "SKILL.md").exists() and (cand / "prompts").is_dir():
            return cand
    for cand in (here, *here.parents):
        if (cand / "pyproject.toml").exists():
            return cand
    return here


def project_root() -> Path:
    return find_project_root()


def references_dir() -> Path:
    return project_root() / "references"


def prompts_dir() -> Path:
    return project_root() / "prompts"


def templates_dir() -> Path:
    return project_root() / "templates"


def markers_path() -> Path:
    return references_dir() / "markers.json"


def require_dir(path: Path, what: str) -> Path:
    if not path.is_dir():
        raise ConfigError(
            f"{what} not found at {path}. "
            f"Run from the skill checkout or set {ENV_HOME} to the paper-humanizer skill directory."
        )
    return path
