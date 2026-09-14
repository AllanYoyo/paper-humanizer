"""Prompt template loading, rendering, and strict JSON extraction.

Templates live in prompts/<name>.prompt.md with a minimal YAML frontmatter
(name/version) and {{placeholder}} bodies. LLM responses must be a single JSON
object; extraction tolerates code fences and surrounding prose but nothing else.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from paper_humanizer import paths
from paper_humanizer.errors import PromptError

_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
_PLACEHOLDER = re.compile(r"\{\{([a-z_]+)\}\}")


@dataclass
class PromptTemplate:
    name: str
    version: str
    body: str
    path: str


def load_prompt(name: str) -> PromptTemplate:
    from paper_humanizer.paths import require_dir

    directory = require_dir(paths.prompts_dir(), "prompts directory")
    path = directory / f"{name}.prompt.md"
    if not path.is_file():
        raise PromptError(f"prompt template not found: {path}")
    raw = path.read_text(encoding="utf-8")
    version = "0"
    body = raw
    match = _FRONT.match(raw)
    if match:
        for line in match.group(1).splitlines():
            if line.startswith("version:"):
                version = line.split(":", 1)[1].strip()
        body = raw[match.end():]
    return PromptTemplate(name=name, version=version, body=body, path=str(path))


def render(template: PromptTemplate, **values: Any) -> str:
    out = template.body
    for key, value in values.items():
        out = out.replace("{{" + key + "}}", str(value))
    leftover = sorted(set(_PLACEHOLDER.findall(out)))
    if leftover:
        raise PromptError(f"unfilled placeholders {leftover} in prompt '{template.name}'")
    return out


def extract_json(text: str) -> dict:
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*[ \t]*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s).strip()
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(s):
        if ch != "{":
            continue
        try:
            obj, _end = decoder.raw_decode(s, idx)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise PromptError(f"no JSON object found in LLM response: {s[:200]!r}")


def ask_json(provider, template_name: str, values: dict, *, system: str | None = None,
             temperature: float = 0.2, max_tokens: int = 4096, attempts: int = 2) -> dict:
    from paper_humanizer.errors import ProviderError

    template = load_prompt(template_name)
    prompt = render(template, **values)
    last_error: Exception | None = None
    for _ in range(max(1, attempts)):
        raw = provider.complete(prompt, system=system, temperature=temperature, max_tokens=max_tokens)
        try:
            return extract_json(raw)
        except PromptError as exc:
            last_error = exc
    raise ProviderError(f"LLM did not return valid JSON after {attempts} attempts: {last_error}")
