"""Web API tests with stdlib HTTP server and scripted providers."""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from paper_humanizer import web
from paper_humanizer.web import WebJobManager, make_server


class FakeProvider:
    available = True

    def __init__(self, rewrite_text: str | None = None):
        self.rewrite_text = rewrite_text

    def complete(self, prompt, *, system=None, temperature=0.2, max_tokens=4096):
        if "SEMANTIC LOCK" in prompt:
            return json.dumps({"atoms": [], "claims": []}, ensure_ascii=False)
        if "AI-flavored" in prompt:
            return json.dumps({"language": "zh", "overall": {"naturalness_score": 3, "summary": "ok"}, "issues": []})
        if "INDEPENDENT judge" in prompt:
            return json.dumps({"claims": [], "naturalness": {"score": 4, "notes": "ok"}, "academic": {"score": 4, "notes": "ok"}, "decision": "pass", "repair_instructions": []})
        return json.dumps({"rewritten_text": self.rewrite_text or "", "change_log": [], "self_check": {}})


@pytest.fixture
def http_server(tmp_path, monkeypatch):
    monkeypatch.delenv("PAPER_HUMANIZER_API_KEY", raising=False)
    monkeypatch.delenv("PAPER_HUMANIZER_MODEL", raising=False)
    monkeypatch.delenv("PAPER_HUMANIZER_BASE_URL", raising=False)
    server, manager = make_server("127.0.0.1", 0, root=tmp_path / "runs")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    yield base, manager
    server.shutdown()
    manager.close()
    server.server_close()
    thread.join(timeout=2)


def request_json(base, path, payload=None):
    if payload is None:
        req = urllib.request.Request(base + path, method="GET")
    else:
        req = urllib.request.Request(base + path, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def test_index_and_static_assets(http_server):
    base, _ = http_server
    req = urllib.request.Request(base + "/", method="GET")
    with urllib.request.urlopen(req) as response:
        assert response.status == 200
        html = response.read().decode()
    assert "paper-humanizer" in html

    req = urllib.request.Request(base + "/static/../SKILL.md", method="GET")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code in {404, 400}


def test_diagnose_validate_and_review(http_server):
    base, _ = http_server
    original = "2020—2024年共调查了327家企业。"
    status, diagnosis = request_json(base, "/api/diagnose", {"text": original})
    assert status == 200
    assert diagnosis["diagnosis"]["language"] == "zh"

    status, validation = request_json(base, "/api/validate", {"original": original, "revised": original})
    assert status == 200
    assert validation["validation"]["passed"] is True

    status, failed = request_json(base, "/api/validate", {"original": original, "revised": original.replace("327", "237")})
    assert status == 200
    assert failed["validation"]["passed"] is False
    assert any(v["rule"] in {"atom_changed", "atom_missing"} for v in failed["validation"]["violations"])

    status, review = request_json(base, "/api/review", {"original": original})
    assert status == 200
    assert "diagnosis" in review


def test_invalid_body_and_size_limit(http_server):
    base, _ = http_server
    status, body = request_json(base, "/api/diagnose", {})
    assert status == 400
    assert "error" in body

    req = urllib.request.Request(base + "/api/diagnose", data=b"not json", headers={"Content-Type": "application/json"}, method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 400

    huge = "x" * (web.MAX_BODY_BYTES + 1)
    status, body = request_json(base, "/api/diagnose", {"text": huge})
    assert status == 413
    assert "large" in body["error"] or "limit" in body["error"]


def test_rewrite_without_provider_returns_failed_job(http_server):
    base, _ = http_server
    status, queued = request_json(base, "/api/rewrite", {"text": "2020年调查了327家企业。", "filename": "paper.md"})
    assert status == 202
    job_id = queued["job_id"]
    for _ in range(30):
        status, result = request_json(base, f"/api/jobs/{job_id}")
        if result["status"] == "failed":
            break
        time.sleep(0.03)
    assert result["status"] == "failed"
    assert "provider" in result["error"].lower()


def test_job_manager_with_fake_provider(monkeypatch, tmp_path):
    original = "2020—2024年共调查了327家企业。值得注意的是，数字化转型显著提升了供应链韧性。"
    revised = "2020—2024年共调查了327家企业。研究显示，数字化转型显著提升了供应链韧性。"
    monkeypatch.setattr(web, "provider_from_env", lambda: FakeProvider(revised))
    manager = WebJobManager(tmp_path / "runs")
    job = manager.submit(original, "paper.md")
    try:
        for _ in range(100):
            current = manager.get(job.job_id)
            if current and current.status in {"success", "reverted", "failed"}:
                break
            time.sleep(0.03)
        assert current.status == "success"
        assert "327家" in current.result["final_text"]
        assert current.result["validation"]["passed"] is True
    finally:
        manager.close()


def test_job_id_cannot_escape_workspace(tmp_path):
    manager = WebJobManager(tmp_path / "runs")
    try:
        assert manager.get("../secret") is None
    finally:
        manager.close()
