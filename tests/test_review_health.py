"""Tests for scripts/review-health.py: the omission rule and its edge cases.

Run: python3 -m unittest tests/test_review_health.py
stdlib only. The rule (`evaluate`) is tested pure; main() against a fake GitHub API.
"""

from __future__ import annotations

import http.server
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import threading
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/review-health.py"
spec = importlib.util.spec_from_file_location("review_health", SCRIPT)
rh = importlib.util.module_from_spec(spec)
sys.modules["review_health"] = rh
spec.loader.exec_module(rh)

NOW = datetime(2026, 10, 2, 3, 0, tzinfo=timezone.utc)
OK = {"payload.json": {"status": "ok"}, "distribute.json": {"push_ingest": {"state": "ok"}, "labels": {"state": "ok"}}}
SKIPPED = {"payload.json": {"status": "skipped"}, "distribute.json": {}}
BRAIN_500 = {"payload.json": {"status": "ok"},
             "distribute.json": {"push_ingest": {"state": "degradado", "http": 500}, "labels": {"state": "ok"}}}
BRAIN_404 = {"payload.json": {"status": "ok"},
             "distribute.json": {"push_ingest": {"state": "degradado", "http": 404}, "labels": {"state": "ok"}}}
NO_KEY = {"payload.json": {"status": "ok"},
          "distribute.json": {"push_ingest": {"state": "sin_clave"}, "labels": {"state": "ok"}}}


def make(n: int, bad: int, bad_files=SKIPPED, conclusion="success", age_days=1, start_id=1000):
    """n runs newest first; the OLDEST `bad` ones are omitted (so the latest is clean)."""
    runs, arts = [], {}
    for i in range(n):
        rid = start_id + i
        runs.append({"id": rid, "conclusion": conclusion, "html_url": f"u/{rid}",
                     "created_at": (NOW - timedelta(days=age_days, minutes=i)).isoformat()})
        arts[rid] = bad_files if i >= n - bad else OK
    return runs, arts


class Rule(unittest.TestCase):
    def ev(self, runs, arts):
        return rh.evaluate(runs, arts, NOW)

    def test_exactly_50_runs_10_omitted_is_green(self):  # 20 % is not > 20 %
        ev = self.ev(*make(50, 10))
        assert (ev["measured"], ev["omitted"], ev["red"]) == (50, 10, [])

    def test_exactly_50_runs_11_omitted_is_red(self):
        ev = self.ev(*make(50, 11))
        assert ev["omitted"] == 11 and len(ev["red"]) == 1 and "11/50" in ev["red"][0]

    def test_more_than_50_runs_only_the_last_50_count(self):
        runs, arts = make(80, 0)
        for r in runs[50:]:  # old omissions outside the window do not count
            arts[r["id"]] = SKIPPED
        ev = self.ev(runs, arts)
        assert ev["considered"] == 50 and ev["omitted"] == 0 and ev["red"] == []

    def test_fewer_than_50_runs_ratio_over_runs_there_are(self):
        assert self.ev(*make(10, 3))["red"]          # 3/10 = 30 %
        assert self.ev(*make(10, 2))["red"] == []    # 2/10 = 20 %, not strictly above
        assert self.ev(*make(5, 1))["red"] == []

    def test_no_runs_is_green_with_note(self):
        ev = self.ev([], {})
        assert ev["red"] == [] and ev["measured"] == 0
        assert "sin runs medibles" in rh.render("o/r", ev)

    def test_brain_5xx_and_4xx_are_counted_as_omissions(self):
        assert self.ev(*make(10, 3, BRAIN_500))["omitted"] == 3
        ev = self.ev(*make(10, 3, BRAIN_404))
        assert ev["omitted"] == 3 and ev["red"]
        assert "HTTP 404" in rh.render("o/r", ev)

    def test_labels_failure_counts(self):
        bad = {"payload.json": {"status": "ok"}, "distribute.json": {"labels": {"state": "degradado", "http": 502}}}
        assert self.ev(*make(10, 3, bad))["omitted"] == 3

    def test_brain_rejected_counts(self):
        bad = {"payload.json": {"status": "ok"}, "distribute.json": {"push_ingest": {"state": "rechazado", "http": 401}}}
        assert self.ev(*make(10, 3, bad))["omitted"] == 3

    def test_missing_key_is_not_an_omission_but_is_reported(self):
        runs, arts = make(10, 0)
        arts = {k: NO_KEY for k in arts}
        ev = self.ev(runs, arts)
        assert ev["omitted"] == 0 and ev["no_key"] == 10 and ev["red"] == []
        assert "SC-1400" in rh.render("o/r", ev)

    def test_degraded_review_counts_and_one_run_two_reasons_counts_once(self):
        both = {"payload.json": {"status": "degraded"},
                "distribute.json": {"push_ingest": {"state": "degradado", "http": 500}}}
        ev = self.ev(*make(10, 3, both))
        assert ev["omitted"] == 3 and ev["measured"] == 10

    def test_run_without_artifact_inside_retention_is_omitted(self):
        runs, arts = make(10, 0)
        arts[runs[9]["id"]] = None
        arts[runs[8]["id"]] = None
        assert self.ev(runs, arts)["omitted"] == 2

    def test_expired_runs_are_left_out_of_both_sides(self):
        runs, arts = make(10, 0)
        old, old_arts = make(40, 0, age_days=30, start_id=5000)
        for r in old:
            old_arts[r["id"]] = None  # artifact gone with retention
        ev = rh.evaluate(runs + old, {**arts, **old_arts}, NOW)
        assert ev["expired"] == 40 and ev["measured"] == 10 and ev["omitted"] == 0

    def test_cancelled_and_skipped_runs_are_not_runs_of_the_window(self):
        runs, arts = make(10, 0)
        junk = [{"id": 9000 + i, "conclusion": c, "created_at": NOW.isoformat()}
                for i, c in enumerate(["cancelled", "skipped", None])]
        ev = rh.evaluate(junk + runs, arts, NOW)
        assert ev["considered"] == 10 and ev["red"] == []

    def test_latest_failure_is_red_even_with_zero_omissions(self):
        runs, arts = make(10, 0)
        runs[0]["conclusion"] = "failure"
        ev = self.ev(runs, arts)
        assert ev["omitted"] == 0 and any("failure" in r for r in ev["red"])

    def test_old_failure_does_not_stay_red(self):
        runs, arts = make(10, 0)
        runs[5]["conclusion"] = "failure"
        assert self.ev(runs, arts)["red"] == []

    def test_inline_contract_step_is_not_an_omission(self):
        # el paso nuevo de review-distribute.py (inline de contratos) vive en distribute.json
        # pero no entra en la regla: la señal mide la review, no cada comentario.
        bad = {"payload.json": {"status": "ok"},
               "distribute.json": {"push_ingest": {"state": "ok"}, "labels": {"state": "ok"},
                                   "inline_contract_findings": {"state": "degradado", "http": 500}}}
        ev = self.ev(*make(10, 0, bad))
        assert ev["omitted"] == 0 and ev["red"] == []


class WorkflowShape(unittest.TestCase):
    """El YAML de la señal nocturna: lista única y ventana calculada (seguimiento D)."""

    WF = (ROOT / ".github/workflows/review-health.yml").read_text()
    LIST = (ROOT / ".github/pr-agent-repos.txt").read_text()

    def test_no_fixed_since_date_in_yaml(self):
        assert "2026-10-02" not in self.WF
        assert "--since 2026" not in self.WF
        assert "date -u -d '24 hours ago'" in self.WF  # la ventana se calcula
        assert '--since "$since"' in self.WF           # y llega al script como variable

    def test_repo_list_comes_from_the_single_file(self):
        assert ".github/pr-agent-repos.txt" in self.WF
        # la lista fija del job `repos` ya no está: ni un `base=` con repos escritos
        assert "base='pocharlies-org/" not in self.WF
        assert "pocharlies-org/skirmshop-labels" not in self.WF  # solo vive en el fichero

    def test_pr_agent_repos_file_is_the_only_list(self):
        repos = [line.strip() for line in self.LIST.splitlines()
                 if line.strip() and not line.strip().startswith("#")]
        assert all(re.fullmatch(r"[\w.-]+/[\w.-]+", r) for r in repos), repos
        assert "pocharlies-org/k8s-litellm-pocharlies" in repos
        assert "pocharlies-org/skirmshop-labels" in repos
        assert len(repos) == len(set(repos))
        # y no hay una segunda lista en el propio workflow
        for r in repos:
            assert self.WF.count(r) == 0, f"{r} duplicado en review-health.yml"


class Selection(unittest.TestCase):
    PA = [{"name": "review / Review del PR (PR-Agent)", "conclusion": "success"}]
    PROPIO = [{"name": "review / Review del PR", "conclusion": "success"},
              {"name": "review / Review del PR (PR-Agent)", "conclusion": "skipped"}]

    def runs(self, n, age_days=1):
        return [{"id": i, "conclusion": "success",
                 "created_at": (NOW - timedelta(days=age_days, minutes=i)).isoformat()} for i in range(n)]

    def test_engine_propio_runs_are_foreign(self):
        runs = self.runs(6)
        jobs = {r["id"]: (self.PA if r["id"] < 2 else self.PROPIO) for r in runs}
        picked, foreign = rh.select_runs(runs, jobs, None)
        assert [r["id"] for r in picked] == [0, 1] and foreign == 4

    def test_window_is_cut_after_filtering(self):
        runs = self.runs(120)
        jobs = {r["id"]: (self.PROPIO if r["id"] < 30 else self.PA) for r in runs}
        picked, foreign = rh.select_runs(runs, jobs, None)
        assert len(picked) == 50 and picked[0]["id"] == 30 and foreign == 30

    def test_since_drops_older_runs(self):
        runs = self.runs(4)
        runs[3]["created_at"] = (NOW - timedelta(days=9)).isoformat()
        picked, foreign = rh.select_runs(runs, {r["id"]: self.PA for r in runs}, NOW - timedelta(days=2))
        assert len(picked) == 3 and foreign == 1

    def test_prueba_marker_runs_are_foreign(self):  # SC-1592
        runs = self.runs(4)
        runs[1]["display_title"] = "[PRUEBA INFRA-332 · NO MERGEAR] value de dgx.hermes.profile-header.v1 sin .vN+1"
        picked, foreign = rh.select_runs(runs, {r["id"]: self.PA for r in runs}, None)
        assert [r["id"] for r in picked] == [0, 2, 3] and foreign == 1

    def test_pr_agent_job_failure_counts_as_ran(self):
        assert rh.engine_ran([{"name": "x (PR-Agent)", "conclusion": "failure"}])
        assert not rh.engine_ran([{"name": "x (PR-Agent)", "conclusion": "skipped"}, {"name": "Review del PR"}])
        assert not rh.engine_ran([])


class _GitHub(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        srv = self.server
        srv.paths.append(self.path)
        if srv.code != 200:
            self.send_response(srv.code); self.end_headers(); return
        if "/jobs?" in self.path:
            body = json.dumps({"jobs": [{"name": "review / Review del PR (PR-Agent)",
                                         "conclusion": "success"}]}).encode()
        elif "/artifacts?" in self.path:
            rid = int(self.path.split("/runs/")[1].split("/")[0])
            body = json.dumps({"artifacts": srv.arts.get(rid, [])}).encode()
        elif self.path.endswith("/zip"):
            body = srv.zip
        else:
            body = json.dumps({"workflow_runs": srv.runs}).encode()
        self.send_response(200); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


class Main(unittest.TestCase):
    def server(self, runs, files=None, code=200, no_artifact_ids=()):
        srv = http.server.HTTPServer(("127.0.0.1", 0), _GitHub)
        srv.runs, srv.paths, srv.code = runs, [], code
        srv.arts = {r["id"]: [{"id": r["id"], "name": f"pr-review-{r['id']}-1", "expired": False}]
                    for r in runs if files is not None and r["id"] not in no_artifact_ids}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name, content in (files or {}).items():
                z.writestr(name, json.dumps(content))
        srv.zip = buf.getvalue()
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown); self.addCleanup(srv.server_close)
        return f"http://127.0.0.1:{srv.server_port}"

    def run_main(self, url, *extra, token="t"):
        e = {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_API_URL")}
        e.update({"GITHUB_API_URL": url, **({"GH_TOKEN": token} if token else {})})
        return subprocess.run([sys.executable, str(SCRIPT), "--repo", "o/r", *extra],
                              capture_output=True, text=True, env=e)

    def recent(self, n, conclusion="success"):
        now = datetime.now(timezone.utc)
        return [{"id": 100 + i, "conclusion": conclusion, "html_url": "u",
                 "created_at": (now - timedelta(hours=i + 1)).isoformat()} for i in range(n)]

    def test_green_exit_0(self):
        r = self.run_main(self.server(self.recent(3), OK))
        assert r.returncode == 0 and "VERDE" in r.stdout, r.stdout + r.stderr

    def test_red_exit_3_when_reviews_omitted(self):
        r = self.run_main(self.server(self.recent(3), SKIPPED))
        assert r.returncode == 3 and "ROJO" in r.stdout

    def test_prueba_contract_tests_do_not_count_as_omitted(self):  # SC-1592
        # 7 runs, 2 of them deliberate contract tests (marker PRUEBA, no artifact): they are
        # `ajeno`, not omissions — 2/7 = 29 % would be red only if they counted.
        runs = self.recent(7)
        for r in runs[1:3]:
            r["display_title"] = "[PRUEBA INFRA-332 · NO MERGEAR] value de dgx.hermes.profile-header.v1 sin .vN+1"
        url = self.server(runs, OK, no_artifact_ids={r["id"] for r in runs[1:3]})
        r = self.run_main(url)
        assert r.returncode == 0 and "VERDE" in r.stdout, r.stdout + r.stderr

    def test_failure_run_red_exit_3(self):
        r = self.run_main(self.server(self.recent(2, "failure"), OK))
        assert r.returncode == 3 and "failure" in r.stdout

    def test_github_403_exit_4(self):
        assert self.run_main(self.server([], code=403)).returncode == 4

    def test_github_down_is_not_green(self):
        assert self.run_main(self.server([], code=502)).returncode == 3

    def test_since_in_the_future_leaves_nothing_to_judge(self):
        r = self.run_main(self.server(self.recent(3), SKIPPED), "--since", "2999-01-01")
        assert r.returncode == 0 and "sin runs medibles" in r.stdout

    def test_bad_since_is_usage(self):
        assert self.run_main(self.server([], None), "--since", "ayer").returncode == 2

    def test_usage_exit_2(self):
        assert self.run_main("http://x", token="").returncode == 2
        assert subprocess.run([sys.executable, str(SCRIPT)], capture_output=True).returncode == 2

    def test_help_and_no_token_leak(self):
        assert subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True).returncode == 0
        r = self.run_main(self.server(self.recent(2), OK), token="sekret-token-xyz")
        assert "sekret-token-xyz" not in r.stdout + r.stderr


if __name__ == "__main__":
    unittest.main()
