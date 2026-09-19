"""Small local web interface for paper-humanizer.

The web layer is intentionally thin: all diagnosis, rewriting, locking and
validation remain in the existing library modules. It is local-first and is
not intended to be exposed directly to the public internet.
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paper_humanizer.diagnose import diagnose_document
from paper_humanizer.errors import PaperHumanizerError
from paper_humanizer.lock import build_lock
from paper_humanizer.normalize import normalize_document
from paper_humanizer.paths import project_root
from paper_humanizer.pipeline import run_rewrite
from paper_humanizer.provider import provider_from_env
from paper_humanizer.review import review_revision, review_single_document
from paper_humanizer.validate import validate_document

MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 2 * 1024 * 1024
MAX_GLOSSARY_TERMS = 200
MAX_QUEUE_SIZE = 4
TERMINAL_STATES = {"success", "reverted", "failed"}


@dataclass
class WebJob:
    job_id: str
    filename: str
    status: str = "queued"
    result: dict[str, Any] | None = None
    error: str | None = None

    def public(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "job_id": self.job_id,
            "filename": self.filename,
            "status": self.status,
        }
        if self.result:
            payload.update(self.result)
        if self.error:
            payload["error"] = self.error
        return payload


class WebJobManager:
    """Bounded in-memory job registry with isolated per-job workspaces."""

    def __init__(self, root: Path | None = None, max_workers: int = 1):
        self.root = (root or (project_root() / ".paper-humanizer" / "web-runs")).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, WebJob] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def submit(self, text: str, filename: str = "paper.md") -> WebJob:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        if len(text) > MAX_TEXT_CHARS:
            raise ValueError(f"text exceeds the {MAX_TEXT_CHARS} character limit")
        with self._lock:
            active = sum(job.status not in TERMINAL_STATES for job in self._jobs.values())
            if active >= MAX_QUEUE_SIZE:
                raise QueueFullError("rewrite queue is full; try again later")
            job_id = secrets.token_urlsafe(16)
            safe_filename = Path(filename or "paper.md").name
            if not safe_filename.lower().endswith((".md", ".markdown", ".txt")):
                safe_filename = "paper.md"
            job = WebJob(job_id=job_id, filename=safe_filename)
            self._jobs[job_id] = job
            job_dir = self.root / job_id
            job_dir.mkdir(parents=True, exist_ok=False)
            input_path = job_dir / "input.md"
            input_path.write_text(normalize_document(text), encoding="utf-8")
            self._executor.submit(self._run, job_id, input_path)
            return job

    def _run(self, job_id: str, input_path: Path) -> None:
        self._set_status(job_id, "running")
        try:
            result = run_rewrite(input_path, provider_from_env())
            payload = {
                "status": result.status,
                "final_text": result.final_text,
                "revised_text": result.revised_text,
                "loops_used": result.loops_used,
                "validation": result.validation.to_dict(),
                "review": result.review,
                "warnings": result.warnings,
                "report": result.report_md,
            }
            self._finish(job_id, payload["status"], payload)
        except Exception as exc:  # job boundary: never kill the worker thread
            self._fail(job_id, f"{type(exc).__name__}: {exc}")

    def _set_status(self, job_id: str, status: str) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].status = status

    def _finish(self, job_id: str, status: str, result: dict[str, Any]) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].status = status
                self._jobs[job_id].result = result

    def _fail(self, job_id: str, error: str) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].status = "failed"
                self._jobs[job_id].error = error

    def get(self, job_id: str) -> WebJob | None:
        with self._lock:
            return self._jobs.get(job_id)


class QueueFullError(RuntimeError):
    """The bounded rewrite queue has reached its configured capacity."""


def _validate_glossary(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_GLOSSARY_TERMS:
        raise ValueError("glossary must be a list with at most 200 terms")
    terms = []
    for term in value:
        if not isinstance(term, str) or not term.strip() or len(term) > 200:
            raise ValueError("each glossary term must be a non-empty string of at most 200 characters")
        terms.append(term.strip())
    return terms


def diagnose_text(text: str) -> dict[str, Any]:
    provider = provider_from_env()
    return diagnose_document(text, provider=provider)


def validate_texts(original: str, revised: str, glossary: list[str] | None = None) -> dict[str, Any]:
    original = normalize_document(original)
    lock = build_lock(original, source="<web>", glossary=glossary or [])
    return validate_document(lock, revised).to_dict()


def review_text(
    original: str,
    revised: str | None = None,
    glossary: list[str] | None = None,
) -> dict[str, Any]:
    original = normalize_document(original)
    result: dict[str, Any] = {"diagnosis": diagnose_text(original), "warnings": []}
    if revised is None:
        result["review"] = review_single_document(provider_from_env(), original)
        return result

    lock = build_lock(original, source="<web>", glossary=glossary or [])
    result["validation"] = validate_document(lock, revised).to_dict()
    provider = provider_from_env()
    if getattr(provider, "available", False):
        try:
            result["preservation_review"] = review_revision(provider, original, revised, lock)
        except Exception as exc:  # deterministic validation remains available
            result["warnings"].append(f"LLM preservation review unavailable: {exc}")
    else:
        result["warnings"].append("LLM preservation review skipped: no provider configured")
    return result


class PaperHumanizerHandler(BaseHTTPRequestHandler):
    manager: WebJobManager
    static_dir: Path

    server_version = "paper-humanizer-web/0.1"

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        # Keep the server usable from a terminal without noisy access logs.
        return

    def _send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(body, "application/json; charset=utf-8", status)

    def _error(self, message: str, status: int) -> None:
        self._send_json({"error": message, "status": status}, status)

    def _read_json(self) -> dict[str, Any] | None:
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or "0")
        except ValueError:
            self._error("invalid Content-Length", 400)
            return None
        if length <= 0:
            self._error("request body is required", 400)
            return None
        if length > MAX_BODY_BYTES:
            # Drain reasonably oversized bodies before responding. This avoids
            # leaving unread bytes on a keep-alive connection (notably on
            # Windows), while refusing to wait for arbitrarily huge bodies.
            if length <= MAX_BODY_BYTES * 2:
                self.rfile.read(length)
            self._error("request body is too large", 413)
            return None
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._error("request body must be valid UTF-8 JSON", 400)
            return None
        if not isinstance(data, dict):
            self._error("JSON body must be an object", 400)
            return None
        return data

    def do_GET(self) -> None:  # noqa: N802
        path = unquote(urlsplit(self.path).path)
        if path == "/":
            self._serve_static("index.html", "text/html; charset=utf-8")
            return
        if path == "/static/style.css":
            self._serve_static("style.css", "text/css; charset=utf-8")
            return
        if path == "/static/app.js":
            self._serve_static("app.js", "text/javascript; charset=utf-8")
            return
        prefix = "/api/jobs/"
        if path.startswith(prefix) and path.count("/") == 3:
            job_id = path[len(prefix):]
            if not job_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in job_id):
                self._error("invalid job id", 400)
                return
            job = self.manager.get(job_id)
            if job is None:
                self._error("job not found", 404)
            else:
                self._send_json(job.public())
            return
        self._error("not found", 404)

    def _serve_static(self, name: str, content_type: str) -> None:
        path = (self.static_dir / name).resolve()
        if self.static_dir.resolve() not in path.parents or not path.is_file():
            self._error("static resource not found", 404)
            return
        self._send_bytes(path.read_bytes(), content_type)

    def do_POST(self) -> None:  # noqa: N802
        path = unquote(urlsplit(self.path).path)
        data = self._read_json()
        if data is None:
            return
        try:
            if path == "/api/diagnose":
                text = _require_text(data, "text")
                self._send_json({"diagnosis": diagnose_text(text)})
                return
            if path == "/api/validate":
                original = _require_text(data, "original")
                revised = _require_text(data, "revised")
                glossary = _validate_glossary(data.get("glossary"))
                self._send_json({"validation": validate_texts(original, revised, glossary)})
                return
            if path == "/api/review":
                original = _require_text(data, "original")
                revised = data.get("revised")
                if revised is not None and not isinstance(revised, str):
                    raise ValueError("revised must be a string when provided")
                glossary = _validate_glossary(data.get("glossary"))
                self._send_json(review_text(original, revised, glossary))
                return
            if path == "/api/rewrite":
                text = _require_text(data, "text")
                filename = data.get("filename", "paper.md")
                if not isinstance(filename, str):
                    raise ValueError("filename must be a string")
                try:
                    job = self.manager.submit(text, filename)
                except QueueFullError as exc:
                    self._error(str(exc), 429)
                    return
                self._send_json(job.public(), 202)
                return
            self._error("not found", 404)
        except ValueError as exc:
            self._error(str(exc), 400)
        except PaperHumanizerError as exc:
            self._error(str(exc), 503)
        except OSError as exc:
            self._error(str(exc), 500)


def _require_text(data: dict[str, Any], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if len(value) > MAX_TEXT_CHARS:
        raise ValueError(f"{name} exceeds the {MAX_TEXT_CHARS} character limit")
    return value


def make_server(host: str = "127.0.0.1", port: int = 8080,
                root: Path | None = None) -> tuple[ThreadingHTTPServer, WebJobManager]:
    manager = WebJobManager(root=root)
    static_dir = project_root() / "web"

    class Handler(PaperHumanizerHandler):
        pass

    Handler.manager = manager
    Handler.static_dir = static_dir
    return ThreadingHTTPServer((host, port), Handler), manager


def serve(host: str = "127.0.0.1", port: int = 8080) -> None:
    server, manager = make_server(host, port)
    print(f"paper-humanizer web: http://{host}:{server.server_port}/")
    print(f"SSH tunnel: ssh -L {server.server_port}:127.0.0.1:{server.server_port} user@vps")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        manager.close()
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local paper-humanizer web interface")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    serve(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
