"""Tests for scripts/review-context.py: exit codes 0/2/4, --dry-run, degradations.

Run: python3 -m unittest tests/test_review_context.py
Cases are pinned fixtures (tests/fixtures/review-context/cases/*): base/ and head/
trees committed into a throwaway git repo, so no live data is involved.
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/review-context.py"
FIX = ROOT / "tests/fixtures/review-context"
REGISTRY = FIX / "registry.yaml"
HEADERS = ["Contratos tocados", "Trailers Contract-Change", "Consumidores del registry",
           "PRs abiertas que solapan", "Degradaciones"]

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


class _GitHub(http.server.BaseHTTPRequestHandler):
    code = 200

    def do_GET(self):
        self.send_response(self.code)
        self.end_headers()
        self.wfile.write(b"[]")

    def log_message(self, *a):
        pass


class ReviewContext(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.tmp = Path(d.name)

    def github(self, code):
        _GitHub.code = code
        srv = http.server.HTTPServer(("127.0.0.1", 0), _GitHub)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_port}"

    def test_value_changed_lists_id_and_consumers(self):
        out = self.tmp / "context.md"
        r = run(make_repo(self.tmp, "value-changed"), out)
        text = out.read_text()
        assert r.returncode == 0, r.stderr
        assert headers(text) == HEADERS
        assert "brain.ingest.v1" in text and "value cambió" in text
        assert text.count("consumers") >= 1 and "synapse-adapter-brain-ingest" in text


    def test_v2_added_and_trailer_facts(self):
        out = self.tmp / "context.md"
        assert run(make_repo(self.tmp, "v2-added"), out).returncode == 0
        text = out.read_text()
        assert "entrada añadida" in text and "`add brain.ingest.v2` — en CONTRACTS.yaml: sí" in text


    def test_exception_block_is_reported(self):
        out = self.tmp / "context.md"
        assert run(make_repo(self.tmp, "exception"), out).returncode == 0
        assert "exception: presente" in out.read_text()


    def test_no_contracts_sections_empty(self):
        out = self.tmp / "context.md"
        assert run(make_repo(self.tmp, "no-contracts"), out).returncode == 0
        text = out.read_text()
        assert headers(text) == HEADERS
        assert text.split("## Contratos tocados")[1].split("##")[0].strip() == "_ninguno_"


    def test_marker_reports_file_and_line(self):
        out = self.tmp / "context.md"
        assert run(make_repo(self.tmp, "marker"), out).returncode == 0
        assert "app.py:2" in out.read_text()


    def test_no_memory_section_and_brain_key_is_ignored(self):
        # SC-4304 S5: el review ya no lee memoria; BRAIN_CI_KEY en el entorno no hace nada ni aparece
        out, key = self.tmp / "context.md", "sekret-key-123"
        r = run(make_repo(self.tmp, "value-changed"), out, env={"BRAIN_CI_KEY": key, "BRAIN_URL": "http://127.0.0.1:1"})
        text = out.read_text()
        assert r.returncode == 0 and "memoria" not in text.lower() and "brain" not in text.split("## Degradaciones", 1)[-1]
        assert key not in r.stdout + r.stderr + text


    def test_missing_registry_degrades_exit_0(self):
        # INFRA-334: sin FRAMEWORK_REPO_TOKEN el paso del registry ni se ejecuta
        # (puerta `if: env.FRAMEWORK_REPO_TOKEN != ''` en el workflow); el
        # contrato que sigue vigente es que registry.yaml ausente NO puede hacer
        # fallar el job: la fuente va a la seccion 6 (Degradaciones) y exit 0.
        out = self.tmp / "context.md"
        repo = make_repo(self.tmp, "value-changed")
        r = run(repo, out, "--registry", str(self.tmp / "nope.yaml"))
        txt = out.read_text()
        assert r.returncode == 0 and "`registry`" in txt
        assert "Aviso · `registry`" in txt.split("## Degradaciones", 1)[-1]


    def test_github_403_exits_4_without_partial_context(self):
        url = self.github(403)
        out = self.tmp / "context.md"
        r = run(make_repo(self.tmp, "value-changed"), out, "--repo", "x/y", "--pr", "1",
                env={"GH_TOKEN": "bad", "GITHUB_API_URL": url})
        text = out.read_text()
        assert r.returncode == 4
        assert headers(text) == HEADERS and "credencial rechazada" in text and "brain.ingest.v1" not in text


    def test_invalid_usage_exit_2(self):
        # Hermetic: in CI GITHUB_EVENT_PATH is set and legitimately supplies base/head.
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_EVENT_PATH"}
        assert subprocess.run([sys.executable, str(SCRIPT), "--out", str(self.tmp / "c.md")],
                              capture_output=True, cwd=self.tmp, env=env).returncode == 2
        assert subprocess.run([sys.executable, str(SCRIPT), "--bogus"], capture_output=True).returncode == 2


    def test_dry_run_headers_in_order_no_git(self):
        out = self.tmp / "context.md"
        r = subprocess.run([sys.executable, str(SCRIPT), "--dry-run", "--repo", "x/y", "--pr", "1",
                            "--registry", str(REGISTRY), "--out", str(out)],
                           capture_output=True, text=True, cwd=self.tmp)
        text = out.read_text()
        assert r.returncode == 0, r.stderr
        assert headers(text) == HEADERS and "- #7 otra PR" in text and "pr_review:" not in text
        assert "consumers" in text


    # ── contract findings inline (seguimiento D del arquitecto, INFRA-332/333) ──

    def findings(self, out: Path) -> list:
        return json.loads((out.parent / "contract-findings.json").read_text())

    def test_value_changed_writes_finding_with_file_line_and_consumers(self):
        out = self.tmp / "context.md"
        repo = make_repo(self.tmp, "value-changed")
        assert run(repo, out).returncode == 0
        f = self.findings(out)
        assert len(f) == 1 and f[0]["id"] == "brain.ingest.v1" and f[0]["file"] == "CONTRACTS.yaml"
        # la línea del `value:` en el CONTRACTS.yaml de head (ancla del comentario inline)
        assert f[0]["line"] == 5, f[0]
        assert f[0]["old_value"] == "brain.{tenant}.ingest" and f[0]["value"] == "brain.{tenant}.ingest_v0"
        assert f[0]["consumers"] == ["synapse-adapter-brain-ingest", "synapse-adapter-brain-summary"]
        assert f[0]["body"].startswith("<!--contrato:brain.ingest.v1-->")
        assert "Severidad alta · contrato `brain.ingest.v1`" in f[0]["body"]
        assert ".vN+1" in f[0]["body"] and "deprecated" in f[0]["body"]
        # context.md también ve la línea (la tabla de la review la cita)
        assert "CONTRACTS.yaml:5" in out.read_text()

    def test_trailer_for_the_id_suppresses_the_finding(self):
        out = self.tmp / "context.md"
        assert run(make_repo(self.tmp, "value-changed-trailer"), out).returncode == 0
        assert self.findings(out) == []
        assert "value cambió" in out.read_text()  # el hecho se sigue reportando

    def test_exception_block_suppresses_the_finding(self):
        out = self.tmp / "context.md"
        assert run(make_repo(self.tmp, "exception"), out).returncode == 0
        assert self.findings(out) == []

    def test_marker_and_added_entries_produce_no_finding(self):
        for case in ("marker", "v2-added", "no-contracts"):
            with self.subTest(case=case):
                d = tempfile.TemporaryDirectory()
                self.addCleanup(d.cleanup)
                tmp = Path(d.name)
                out = tmp / "context.md"
                assert run(make_repo(tmp, case), out).returncode == 0
                assert self.findings(out) == []

    def test_dry_run_writes_findings_file_too(self):
        out = self.tmp / "context.md"
        r = subprocess.run([sys.executable, str(SCRIPT), "--dry-run", "--repo", "x/y", "--pr", "1",
                            "--registry", str(REGISTRY), "--out", str(out)],
                           capture_output=True, text=True, cwd=self.tmp)
        assert r.returncode == 0, r.stderr
        # el fixture dry-run trae trailer para el mismo id: suprimido, pero el fichero existe
        assert self.findings(out) == []

    def test_size_capped_and_degradations_kept(self):
        ctx = {"touched": [], "trailers": [], "consumers": {}, "prs": [],
               "degraded": [("github", "x")]}
        ctx["prs"] = [{"number": i, "title": "t" * 300, "branch": "b", "files": ["f" * 200] * 40} for i in range(60)]
        text = rc.render(ctx)
        assert len(text.encode()) <= 20 * 1024 and "`github`: x" in text

if __name__ == "__main__":
    unittest.main()
