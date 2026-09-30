"""Tests for scripts/review-context.py: exit codes 0/2/4, --dry-run, degradations.

Run: python -m pytest tests/test_review_context.py -q
Cases are pinned fixtures (tests/fixtures/review-context/cases/*): base/ and head/
trees committed into a throwaway git repo, so no live data is involved.
"""

from __future__ import annotations

import http.server
import importlib.util
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/review-context.py"
FIX = ROOT / "tests/fixtures/review-context"
REGISTRY = FIX / "registry.yaml"
HEADERS = ["Contratos tocados", "Trailers Contract-Change", "Consumidores del registry",
           "PRs abiertas que solapan", "Memoria local-ops", "Degradaciones"]

spec = importlib.util.spec_from_file_location("review_context", SCRIPT)
rc = importlib.util.module_from_spec(spec)
sys.modules["review_context"] = rc
spec.loader.exec_module(rc)


def sh(cwd: Path, *cmd: str) -> None:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    assert r.returncode == 0, f"{cmd}: {r.stdout}{r.stderr}"


def make_repo(tmp: Path, case: str) -> Path:
    repo, src = tmp / "repo", FIX / "cases" / case
    repo.mkdir()
    sh(repo, "git", "init", "-q", "-b", "main")
    sh(repo, "git", "config", "core.hooksPath", "/dev/null")
    shutil.copytree(src / "base", repo, dirs_exist_ok=True)
    sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-qm", "base")
    for p in repo.iterdir():
        if p.name != ".git":
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    shutil.copytree(src / "head", repo, dirs_exist_ok=True)
    sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-qF", str(src / "commit-msg"))
    return repo


def run(repo: Path, out: Path, *extra: str, env: dict | None = None):
    e = {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "BRAIN_CI_KEY", "GITHUB_EVENT_PATH")}
    e.update(env or {})
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--base", "HEAD~1", "--head", "HEAD", "--workdir", str(repo),
         "--registry", str(REGISTRY), "--out", str(out), *extra],
        capture_output=True, text=True, env=e, cwd=repo)


def headers(text: str) -> list[str]:
    return [l[3:] for l in text.splitlines() if l.startswith("## ")]


def test_value_changed_lists_id_and_consumers(tmp_path):
    out = tmp_path / "context.md"
    r = run(make_repo(tmp_path, "value-changed"), out)
    text = out.read_text()
    assert r.returncode == 0, r.stderr
    assert headers(text) == HEADERS
    assert "brain.ingest.v1" in text and "value cambió" in text
    assert text.count("consumers") >= 1 and "synapse-adapter-brain-ingest" in text


def test_v2_added_and_trailer_facts(tmp_path):
    out = tmp_path / "context.md"
    assert run(make_repo(tmp_path, "v2-added"), out).returncode == 0
    text = out.read_text()
    assert "entrada añadida" in text and "`add brain.ingest.v2` — en CONTRACTS.yaml: sí" in text


def test_exception_block_is_reported(tmp_path):
    out = tmp_path / "context.md"
    assert run(make_repo(tmp_path, "exception"), out).returncode == 0
    assert "exception: presente" in out.read_text()


def test_no_contracts_sections_empty(tmp_path):
    out = tmp_path / "context.md"
    assert run(make_repo(tmp_path, "no-contracts"), out).returncode == 0
    text = out.read_text()
    assert headers(text) == HEADERS
    assert text.split("## Contratos tocados")[1].split("##")[0].strip() == "_ninguno_"


def test_marker_reports_file_and_line(tmp_path):
    out = tmp_path / "context.md"
    assert run(make_repo(tmp_path, "marker"), out).returncode == 0
    assert "app.py:2" in out.read_text()


def test_degraded_without_brain_key_exit_0(tmp_path):
    out = tmp_path / "context.md"
    r = run(make_repo(tmp_path, "value-changed"), out)
    assert r.returncode == 0
    assert "`brain`: sin BRAIN_CI_KEY" in out.read_text()


def test_missing_registry_degrades_exit_0(tmp_path):
    out = tmp_path / "context.md"
    repo = make_repo(tmp_path, "value-changed")
    r = run(repo, out, "--registry", str(tmp_path / "nope.yaml"))
    assert r.returncode == 0 and "`registry`" in out.read_text()


def test_brain_down_and_secret_not_printed(tmp_path):
    out, key = tmp_path / "context.md", "sekret-key-123"
    r = run(make_repo(tmp_path, "value-changed"), out,
            env={"BRAIN_CI_KEY": key, "BRAIN_URL": "http://127.0.0.1:1"})
    assert r.returncode == 0
    assert "`brain`" in out.read_text()
    assert key not in r.stdout + r.stderr + out.read_text()


class _Brain(http.server.BaseHTTPRequestHandler):
    code, payload = 200, b""

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(self.code)
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, *a):
        pass


@pytest.fixture
def brain():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Brain)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_brain_ok_cites_hits_in_documents_key(tmp_path, brain):
    srv, url = brain
    _Brain.code = 200
    _Brain.payload = (b'{"instance_id":"local-ops","documents":[{"text":"memoria  previa","score":1,'
                      b'"metadata":{"source_id":"pr_review:x/y#1"}},{"text":"ajeno","score":1,'
                      b'"metadata":{"instance_id":"otra","source_id":"z"}}]}')
    out = tmp_path / "context.md"
    r = run(make_repo(tmp_path, "value-changed"), out, env={"BRAIN_CI_KEY": "k", "BRAIN_URL": url})
    text = out.read_text()
    assert r.returncode == 0
    assert "- [pr_review:x/y#1] memoria previa" in text and "ajeno" not in text


def test_brain_403_exits_4_without_partial_context(tmp_path, brain):
    srv, url = brain
    _Brain.code, _Brain.payload = 403, b"{}"
    out = tmp_path / "context.md"
    r = run(make_repo(tmp_path, "value-changed"), out, env={"BRAIN_CI_KEY": "bad", "BRAIN_URL": url})
    text = out.read_text()
    assert r.returncode == 4
    assert headers(text) == HEADERS and "credencial rechazada" in text and "brain.ingest.v1" not in text


def test_invalid_usage_exit_2(tmp_path):
    assert subprocess.run([sys.executable, str(SCRIPT), "--out", str(tmp_path / "c.md")],
                          capture_output=True, cwd=tmp_path).returncode == 2
    assert subprocess.run([sys.executable, str(SCRIPT), "--bogus"], capture_output=True).returncode == 2


def test_dry_run_six_headers_in_order_no_git(tmp_path):
    out = tmp_path / "context.md"
    r = subprocess.run([sys.executable, str(SCRIPT), "--dry-run", "--repo", "x/y", "--pr", "1",
                        "--registry", str(REGISTRY), "--out", str(out)],
                       capture_output=True, text=True, cwd=tmp_path)
    text = out.read_text()
    assert r.returncode == 0, r.stderr
    assert headers(text) == HEADERS and "- #7 otra PR" in text and "- [pr_review:x/y#3]" in text
    assert "consumers" in text


def test_size_capped_and_degradations_kept():
    ctx = {"touched": [], "trailers": [], "consumers": {}, "prs": [],
           "memory": [{"source": "s", "summary": "m" * 200}] * 5, "degraded": [("brain", "x")]}
    ctx["prs"] = [{"number": i, "title": "t" * 300, "branch": "b", "files": ["f" * 200] * 40} for i in range(60)]
    text = rc.render(ctx)
    assert len(text.encode()) <= 20 * 1024 and "`brain`: x" in text
