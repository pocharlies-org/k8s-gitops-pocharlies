"""Tests for scripts/review-distribute.py: payload contract, exit codes 0/2/4, labels, push-ingest.

Run: python3 -m unittest tests/test_review_distribute.py
stdlib only. GitHub and the brain are local HTTP servers: no live data.
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/review-distribute.py"
SCHEMA = json.loads((ROOT / "schemas/pr_review.v1.json").read_text())
REVIEW = ROOT / "tests/fixtures/review-distribute/review.md"

spec = importlib.util.spec_from_file_location("review_distribute", SCRIPT)
rd = importlib.util.module_from_spec(spec)
sys.modules["review_distribute"] = rd
spec.loader.exec_module(rd)


class _Server(http.server.BaseHTTPRequestHandler):
    def _do(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n)) if n else None
        self.server.calls.append((self.command, self.path, body, dict(self.headers)))
        self.send_response(self.server.code)
        self.end_headers()
        self.wfile.write(b"{}")

    do_POST = do_DELETE = _do

    def log_message(self, *a):
        pass


class _Labels(http.server.BaseHTTPRequestHandler):
    """GitHub with state: POST adds a label, DELETE removes it (404 if absent)."""

    def _do(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n)) if n else None
        labels = self.server.labels
        code = 200
        if self.command == "POST":
            labels.update(body["labels"])
        else:
            name = urllib.parse.unquote(self.path.rsplit("/", 1)[1])
            code = 200 if name in labels else 404
            labels.discard(name)
        self.send_response(code)
        self.end_headers()
        self.wfile.write(b"{}")

    do_POST = do_DELETE = _do

    def log_message(self, *a):
        pass


class _Comments(http.server.BaseHTTPRequestHandler):
    """GitHub con estado de comentarios en línea del PR: GET lista, POST crea,
    DELETE /pulls/comments/<id> borra (404 si no estaba). `code` distinto de 200
    responde ese código a todo (para probar degradado y 401/403)."""

    def _all(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n)) if n else None
        srv = self.server
        srv.calls.append((self.command, self.path.split("?")[0], body))
        code, payload = srv.code, b"{}"
        if srv.code == 200:
            if "/issues/" in self.path:  # el paso de etiquetas: se acepta y se ignora
                code, payload = 200, b"{}"
            elif self.command == "GET":
                code, payload = 200, json.dumps(srv.comments).encode()
            elif self.command == "POST":
                cid = srv.next_id
                srv.next_id += 1
                srv.comments.append({"id": cid, **body,
                                     "pull_request_review": {"commit_id": body["commit_id"]}})
                code, payload = 201, b"{}"
            elif self.command == "DELETE":
                cid = int(self.path.rsplit("/", 1)[1])
                before = len(srv.comments)
                srv.comments = [c for c in srv.comments if c["id"] != cid]
                code, payload = (204 if before != len(srv.comments) else 404), b""
        self.send_response(code)
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    do_GET = do_POST = do_DELETE = _all

    def log_message(self, *a):
        pass


class ReviewDistribute(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.out = Path(d.name) / ".review"

    def server(self, code: int = 200):
        srv = http.server.HTTPServer(("127.0.0.1", 0), _Server)
        srv.calls, srv.code = [], code
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        return srv, f"http://127.0.0.1:{srv.server_port}"

    def run_script(self, *extra: str, env: dict | None = None):
        e = {k: v for k, v in os.environ.items()
             if k not in ("GH_TOKEN", "BRAIN_CI_KEY", "BRAIN_URL", "GITHUB_API_URL", "GITHUB_EVENT_PATH")}
        e.update(env or {})
        return subprocess.run([sys.executable, str(SCRIPT), "--out-dir", str(self.out), *extra],
                              capture_output=True, text=True, env=e)

    def payload(self) -> dict:
        return json.loads((self.out / "payload.json").read_text())

    # ── dry-run and contract ──

    def test_dry_run_writes_valid_payload_and_notify(self):
        r = self.run_script("--dry-run", "--repo", "o/r", "--pr", "7", "--review-md", str(REVIEW))
        assert r.returncode == 0, r.stderr
        p = self.payload()
        assert rd.validate(p, SCHEMA) == []
        assert p["schema"] == "pr_review.v1" and p["status"] == "ok"
        assert p["merge_recommendation"] == "changes_required" and p["changes_required"] is True
        assert p["possible_security_issue"] is True
        assert p["findings"][0] == {"file": "src/db.py", "line": 42, "severity": "high",
                                    "summary": "string-concatenated query with user input"}
        assert len(p["findings"]) == 2
        notify = (self.out / "notify.txt").read_text()
        assert notify.startswith("o/r#7 · recomendación: changes_required · 2 hallazgos")
        assert "https://github.com/o/r/pull/7" in notify and "\x1b" not in notify
        assert len(notify.splitlines()) <= 3

    def test_dry_run_without_review_uses_fixture(self):
        assert self.run_script("--dry-run", "--repo", "x/y", "--pr", "1").returncode == 0
        assert self.payload()["status"] == "ok"

    def test_schema_rejects_bad_payload(self):
        p = {**self.dry(), "status": "maybe", "extra": 1}
        errs = rd.validate(p, SCHEMA)
        assert any("status" in e for e in errs) and any("extra" in e for e in errs)

    def dry(self) -> dict:
        return rd.build_payload("o/r", 1, "a" * 40, REVIEW)

    def test_missing_review_is_skipped_and_blocks_nothing(self):
        srv, url = self.server()
        r = self.run_script("--repo", "o/r", "--pr", "3", "--head-sha", "abc", "--review-md", "/nonexistent",
                            env={"GH_TOKEN": "t", "GITHUB_API_URL": url})
        assert r.returncode == 0, r.stderr
        p = self.payload()
        assert p["status"] == "skipped" and p["merge_recommendation"] == "unknown"
        assert p["changes_required"] is False and p["possible_security_issue"] is False
        assert [c[0] for c in srv.calls] == ["DELETE", "DELETE"]  # a dead review clears both labels

    def test_empty_review_is_degraded(self):
        f = self.out.parent / "empty.md"
        f.write_text("  \n")
        assert self.run_script("--dry-run", "--repo", "o/r", "--pr", "3", "--review-md", str(f)).returncode == 0
        assert self.payload()["status"] == "degraded"

    def test_content_capped_at_12kb_fields_kept(self):
        f = self.out.parent / "big.md"
        f.write_text(REVIEW.read_text() + ("ñ" * 20000))
        assert self.run_script("--dry-run", "--repo", "o/r", "--pr", "3", "--review-md", str(f)).returncode == 0
        p = self.payload()
        assert len(p["content"].encode()) <= 12 * 1024 and rd.validate(p, SCHEMA) == []
        assert p["merge_recommendation"] == "changes_required"

    def test_security_negative_is_false(self):
        f = self.out.parent / "ok.md"
        f.write_text("Merge recommendation: merge\nSecurity concerns: No\n")
        assert self.run_script("--dry-run", "--repo", "o/r", "--pr", "3", "--review-md", str(f)).returncode == 0
        p = self.payload()
        assert p["merge_recommendation"] == "merge" and p["possible_security_issue"] is False
        assert p["changes_required"] is False

    # ── brain and labels ──

    def test_without_brain_key_degrades_exit_0_and_syncs_labels(self):
        srv, url = self.server()
        r = self.run_script("--repo", "o/r", "--pr", "7", "--head-sha", "abc", "--review-md", str(REVIEW),
                            env={"GH_TOKEN": "t", "GITHUB_API_URL": url})
        assert r.returncode == 0, r.stderr
        assert "sin BRAIN_CI_KEY" in r.stdout
        assert (self.out / "payload.json").is_file() and (self.out / "notify.txt").is_file()
        calls = [(m, p, b) for m, p, b, _ in srv.calls]
        assert ("POST", "/repos/o/r/issues/7/labels", {"labels": ["changes_required"]}) in calls
        assert ("POST", "/repos/o/r/issues/7/labels", {"labels": ["possible security issue"]}) in calls

    def stale_labels(self, review: Path | None, extra=()):
        """Run live against a GitHub that already has both labels on the PR; return (rc, labels left)."""
        srv = http.server.HTTPServer(("127.0.0.1", 0), _Labels)
        srv.labels = {"changes_required", "possible security issue", "bug"}
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        args = ["--repo", "o/r", "--pr", "7", "--head-sha", "abc", *extra]
        if review:
            args += ["--review-md", str(review)]
        r = self.run_script(*args, env={"GH_TOKEN": "t", "GITHUB_API_URL": f"http://127.0.0.1:{srv.server_port}"})
        return r.returncode, srv.labels

    def test_status_not_ok_removes_stale_labels_and_payload_is_false(self):
        # INFRA-353 relies on this: a changes_required left by an earlier green review
        # must not survive a run whose review did not happen.
        self.out.parent.mkdir(parents=True, exist_ok=True)
        empty = self.out.parent / "empty.md"
        empty.write_text("\n")
        blank = self.out.parent / "blank.md"
        blank.write_text("   \n\t\n")
        for name, review, status in (("degraded-empty", empty, "degraded"),
                                     ("degraded-blank", blank, "degraded"),
                                     ("skipped-missing", self.out.parent / "nope.md", "skipped"),
                                     ("skipped-no-flag", None, "skipped")):
            with self.subTest(name):
                rc, labels = self.stale_labels(review)
                assert rc == 0
                assert labels == {"bug"}, labels  # both ours gone, the foreign one untouched
                p = self.payload()
                assert p["status"] == status and p["changes_required"] is False
                assert p["possible_security_issue"] is False and p["merge_recommendation"] == "unknown"

    def test_status_ok_keeps_the_labels_the_review_asks_for(self):
        rc, labels = self.stale_labels(REVIEW)
        assert rc == 0 and labels == {"changes_required", "possible security issue", "bug"}

    def test_invariants_reject_blocking_payload_with_status_not_ok(self):
        p = self.dry()
        for status in ("degraded", "skipped"):
            bad = {**p, "status": status}  # still says changes_required
            assert rd.invariants(bad), status
        assert rd.invariants({**p, "status": "degraded", "merge_recommendation": "unknown",
                              "changes_required": False, "possible_security_issue": True})
        assert rd.invariants({**p, "changes_required": False})  # recommendation says it is required
        assert rd.invariants(p) == []

    def test_labels_removed_when_review_clean(self):
        f = self.out.parent / "ok.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("Merge recommendation: merge\nSecurity concerns: No\n")
        srv, url = self.server()
        r = self.run_script("--repo", "o/r", "--pr", "7", "--head-sha", "abc", "--review-md", str(f),
                            env={"GH_TOKEN": "t", "GITHUB_API_URL": url})
        assert r.returncode == 0, r.stderr
        assert [(m, p) for m, p, _, _ in srv.calls] == [
            ("DELETE", "/repos/o/r/issues/7/labels/changes_required"),
            ("DELETE", "/repos/o/r/issues/7/labels/possible%20security%20issue")]

    def test_push_ingest_shape(self):
        gh, gh_url = self.server()
        brain, brain_url = self.server()
        r = self.run_script("--repo", "o/r", "--pr", "7", "--head-sha", "abc", "--review-md", str(REVIEW),
                            env={"GH_TOKEN": "t", "GITHUB_API_URL": gh_url,
                                 "BRAIN_URL": brain_url, "BRAIN_CI_KEY": "sekret-key-123"})
        assert r.returncode == 0, r.stderr
        m, path, body, hdrs = brain.calls[0]
        assert (m, path) == ("POST", "/instances/local-ops/push-ingest")
        assert body["adapter"] == "pr_review"
        doc = body["documents"][0]
        assert doc["source_id"] == "pr_review:o/r#7"
        assert doc["content"] == self.payload()["content"] and len(doc["content"].encode()) <= 12 * 1024
        meta = doc["metadata"]
        assert "content" not in meta and meta["schema"] == "pr_review.v1"
        assert meta["changes_required"] is True and meta["findings"][0]["file"] == "src/db.py"
        assert "sekret-key-123" not in r.stdout + r.stderr

    def dist(self) -> dict:
        return json.loads((self.out / "distribute.json").read_text())

    def test_distribute_json_records_each_step(self):
        gh, gh_url = self.server()
        brain, brain_url = self.server(code=404)
        r = self.run_script("--repo", "o/r", "--pr", "7", "--head-sha", "abc", "--review-md", str(REVIEW),
                            env={"GH_TOKEN": "t", "GITHUB_API_URL": gh_url,
                                 "BRAIN_URL": brain_url, "BRAIN_CI_KEY": "k"})
        assert r.returncode == 0
        assert self.dist() == {"push_ingest": {"state": "degradado", "http": 404},
                               "labels": {"state": "ok", "http": None}}

    def test_distribute_json_without_key_and_on_rejection(self):
        gh, gh_url = self.server(code=403)
        assert self.run_script("--repo", "o/r", "--pr", "7", "--head-sha", "abc", "--review-md", str(REVIEW),
                               env={"GH_TOKEN": "t", "GITHUB_API_URL": gh_url}).returncode == 4
        assert self.dist() == {"push_ingest": {"state": "sin_clave", "http": None},
                               "labels": {"state": "rechazado", "http": 403}}

    def test_brain_failure_degrades_exit_0(self):
        gh, gh_url = self.server()
        brain, brain_url = self.server(code=500)
        r = self.run_script("--repo", "o/r", "--pr", "7", "--head-sha", "abc", "--review-md", str(REVIEW),
                            env={"GH_TOKEN": "t", "GITHUB_API_URL": gh_url,
                                 "BRAIN_URL": brain_url, "BRAIN_CI_KEY": "sekret-key-123"})
        assert r.returncode == 0 and "push-ingest: degradado" in r.stdout

    def test_github_403_exit_4_files_still_written(self):
        srv, url = self.server(code=403)
        r = self.run_script("--repo", "o/r", "--pr", "7", "--head-sha", "abc", "--review-md", str(REVIEW),
                            env={"GH_TOKEN": "t", "GITHUB_API_URL": url})
        assert r.returncode == 4, r.stdout + r.stderr
        assert (self.out / "payload.json").is_file() and (self.out / "notify.txt").is_file()

    def test_brain_401_exit_4_but_labels_still_synced(self):
        gh, gh_url = self.server()
        brain, brain_url = self.server(code=401)
        r = self.run_script("--repo", "o/r", "--pr", "7", "--head-sha", "abc", "--review-md", str(REVIEW),
                            env={"GH_TOKEN": "t", "GITHUB_API_URL": gh_url,
                                 "BRAIN_URL": brain_url, "BRAIN_CI_KEY": "k"})
        assert r.returncode == 4, r.stdout + r.stderr
        assert len(gh.calls) == 2 and all(c[0] == "POST" for c in gh.calls)

    def test_github_403_exit_4_but_push_ingest_still_attempted(self):
        gh, gh_url = self.server(code=403)
        brain, brain_url = self.server()
        r = self.run_script("--repo", "o/r", "--pr", "7", "--head-sha", "abc", "--review-md", str(REVIEW),
                            env={"GH_TOKEN": "t", "GITHUB_API_URL": gh_url,
                                 "BRAIN_URL": brain_url, "BRAIN_CI_KEY": "k"})
        assert r.returncode == 4, r.stdout + r.stderr
        assert [c[1] for c in brain.calls] == ["/instances/local-ops/push-ingest"]

    # ── inline contract findings (seguimiento D del arquitecto, INFRA-332/333) ──

    def comments_server(self, code: int = 200):
        srv = http.server.HTTPServer(("127.0.0.1", 0), _Comments)
        srv.calls, srv.comments, srv.next_id, srv.code = [], [], 500, code
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        return srv, f"http://127.0.0.1:{srv.server_port}"

    def findings_file(self, findings=None, line: int = 5):
        if findings is None:
            findings = [{"id": "brain.ingest.v1", "file": "CONTRACTS.yaml", "line": line,
                         "old_value": "brain.a", "value": "brain.b", "consumers": ["synapse-x"],
                         "body": "<!--contrato:brain.ingest.v1-->\n**Severidad alta · contrato "
                                 "`brain.ingest.v1`**: el value no muta"}]
        f = self.out.parent / "contract-findings.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(findings))
        return f

    def inline(self, review: Path | None = None, code: int = 200):
        srv, url = self.comments_server(code=code)
        f = self.findings_file()
        args = ["--repo", "o/r", "--pr", "7", "--head-sha", "abc", "--findings", str(f)]
        if review:
            args += ["--review-md", str(review)]
        r = self.run_script(*args, env={"GH_TOKEN": "t", "GITHUB_API_URL": url})
        return r, srv, url, f

    def test_inline_finding_posted_anchored_to_head_line(self):
        r, srv, _, _ = self.inline(REVIEW)
        assert r.returncode == 0, r.stdout + r.stderr
        posts = [c for c in srv.calls if c[0] == "POST" and c[1] == "/repos/o/r/pulls/7/comments"]
        assert len(posts) == 1, srv.calls
        body = posts[0][2]
        assert body["path"] == "CONTRACTS.yaml" and body["line"] == 5 and body["side"] == "RIGHT"
        assert body["commit_id"] == "abc" and body["body"].startswith("<!--contrato:brain.ingest.v1-->")
        assert self.dist()["inline_contract_findings"]["state"] == "ok"
        assert "hallazgos inline: ok" in r.stdout
        # la review sigue su camino: etiquetas y payload igual que sin findings
        assert self.payload()["status"] == "ok"
        assert any(c[1] == "/repos/o/r/issues/7/labels" for c in srv.calls)

    def test_inline_finding_not_reposted_when_unchanged(self):
        r, srv, url, f = self.inline(REVIEW)
        assert r.returncode == 0
        n_posts = len([c for c in srv.calls if c[0] == "POST" and "/pulls/7/comments" in c[1]])
        assert n_posts == 1
        before = len(srv.calls)
        r2 = self.run_script("--repo", "o/r", "--pr", "7", "--head-sha", "abc",
                             "--findings", str(f), "--review-md", str(REVIEW),
                             env={"GH_TOKEN": "t", "GITHUB_API_URL": url})
        assert r2.returncode == 0, r2.stderr
        new = srv.calls[before:]
        assert [c[0] for c in new if "/pulls/7/comments" in c[1]] == ["GET"]  # solo se mira
        assert "1 en su sitio" in r2.stdout
        assert len(srv.comments) == 1  # ni duplicado ni movido

    def test_inline_finding_reposted_when_line_or_head_changes(self):
        r, srv, url, f = self.inline(REVIEW)
        assert r.returncode == 0
        self.findings_file(line=6)  # el value se movió de línea en el nuevo push
        r2 = self.run_script("--repo", "o/r", "--pr", "7", "--head-sha", "def",
                             "--findings", str(f), "--review-md", str(REVIEW),
                             env={"GH_TOKEN": "t", "GITHUB_API_URL": url})
        assert r2.returncode == 0, r2.stderr
        verbs = [c[0] for c in srv.calls if c[1].startswith("/repos/o/r/pulls/comments/")]
        assert verbs == ["DELETE"]
        posts = [c for c in srv.calls if c[0] == "POST" and c[1] == "/repos/o/r/pulls/7/comments"]
        assert len(posts) == 2 and posts[1][2]["line"] == 6 and posts[1][2]["commit_id"] == "def"
        assert len(srv.comments) == 1  # el viejo fuera, el nuevo en su sitio

    def inline_with(self, findings):
        srv, url = self.comments_server()
        f = self.findings_file(findings)
        r = self.run_script("--repo", "o/r", "--pr", "7", "--head-sha", "abc",
                            "--findings", str(f), "--review-md", str(REVIEW),
                            env={"GH_TOKEN": "t", "GITHUB_API_URL": url})
        return r, srv, url, f

    def test_inline_empty_findings_recorded_not_posted(self):
        r, srv, _, _ = self.inline_with([])
        assert r.returncode == 0
        assert self.dist()["inline_contract_findings"] == {"state": "sin_hallazgos", "http": None}
        assert not [c for c in srv.calls if c[0] == "POST" and "/pulls/7/comments" in c[1]]

    def test_inline_github_500_degrades_exit_0(self):
        r, srv, _, _ = self.inline(REVIEW, code=500)
        assert r.returncode == 0, r.stdout + r.stderr
        rec = self.dist()["inline_contract_findings"]
        assert rec["state"] == "degradado" and rec["http"] == 500
        assert "hallazgos inline: degradado" in r.stdout

    def test_inline_github_403_exit_4_recorded(self):
        r, srv, _, _ = self.inline(REVIEW, code=403)
        assert r.returncode == 4, r.stdout + r.stderr
        rec = self.dist()["inline_contract_findings"]
        assert rec["state"] == "rechazado" and rec["http"] == 403

    def test_invalid_findings_file_is_usage_2(self):
        srv, url = self.comments_server()
        f = self.findings_file()
        f.write_text('[{"id": "sin-line"}]')
        r = self.run_script("--repo", "o/r", "--pr", "7", "--head-sha", "abc",
                            "--findings", str(f), env={"GH_TOKEN": "t", "GITHUB_API_URL": url})
        assert r.returncode == 2 and "contract-findings" in r.stderr

    def test_dry_run_with_findings_no_network(self):
        f = self.findings_file()
        r = self.run_script("--dry-run", "--repo", "o/r", "--pr", "7", "--findings", str(f))
        assert r.returncode == 0, r.stderr
        assert self.dist()["inline_contract_findings"] == {"state": "dry_run", "http": None,
                                                           "posted": 1}

    def test_without_findings_flag_no_inline_record(self):
        srv, url = self.comments_server()
        r = self.run_script("--repo", "o/r", "--pr", "7", "--head-sha", "abc",
                            "--review-md", str(REVIEW), env={"GH_TOKEN": "t", "GITHUB_API_URL": url})
        assert r.returncode == 0, r.stderr
        assert "inline_contract_findings" not in self.dist()

    # ── usage ──

    def test_usage_errors_exit_2(self):
        assert self.run_script("--dry-run", "--pr", "1").returncode == 2           # no --repo
        assert self.run_script("--dry-run", "--repo", "bad", "--pr", "1").returncode == 2
        assert self.run_script("--repo", "o/r", "--pr", "1", "--head-sha", "a").returncode == 2  # no GH_TOKEN
        assert self.run_script("--repo", "o/r", "--pr", "1", env={"GH_TOKEN": "t"}).returncode == 2  # no head

    def test_help_exit_0(self):
        assert self.run_script("--help").returncode == 0


if __name__ == "__main__":
    unittest.main()
