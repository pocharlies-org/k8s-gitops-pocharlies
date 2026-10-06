#!/usr/bin/env python3
"""Tests de la librería de cola de CI (INFRA-547). Hermetic: fixtures JSON +
transporte inyectable; nunca llama a la API. Patrón unittest del repo."""

import datetime as dt
import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ci-queue"))
import ci_queue as cq  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ci-queue"
ORG = "pocharlies-org"
NOW = dt.datetime(2026, 10, 5, 12, 0, 0, tzinfo=dt.timezone.utc)
SINCE = NOW - dt.timedelta(days=7)


def fixture_transport(calls=None):
    """Transporte que sirve los fixtures por path; `calls` registra lo pedido."""
    def transport(url, headers):
        if calls is not None:
            calls.append(url)
        path = url.split("?")[0].replace(cq.API, "")
        params = dict(p.split("=", 1) for p in url.split("?", 1)[1:]
                      for p in [p]) if "?" in url else {}
        if path.endswith("/repos") and "/orgs/" in path:
            name = "repos.json"
        elif path.endswith("/actions/runs"):
            name = (f"{params.get('repo', path.split('/')[3])}__"
                    + ("runs-queued.json" if params.get("status") == "queued" else "runs.json"))
        elif path.endswith("/jobs"):
            parts = path.split("/")
            repo, run_id = parts[3], parts[6]
            attempt = params.get("attempt")
            name = f"{repo}__{run_id}__jobs{('__' + attempt) if attempt else ''}.json"
        else:
            raise AssertionError(f"path sin fixture: {path}")
        f = FIXTURES / name
        if not f.exists():
            return 404, {}, b'{"message": "no fixture"}'
        return 200, {"X-RateLimit-Remaining": "4000"}, f.read_bytes()
    return transport


def fixture_client():
    return cq.Client(token="t", transport=fixture_transport())


def job(**kw):
    base = dict(repo="r", run_id=1, run_number=1, attempt=1, workflow="ci",
                event="push", branch="main", name="j", labels=("arc-k8s",),
                created_at=dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc),
                started_at=None, completed_at=None, status="completed",
                conclusion=None, wait=0.0, queued_now=False)
    base.update(kw)
    return cq.Job(**base)


class TestPercentiles(unittest.TestCase):
    def test_known_values(self):
        v = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        self.assertEqual(cq.percentile(v, 50), 50)
        self.assertEqual(cq.percentile(v, 95), 100)
        self.assertEqual(cq.percentile(v, 1), 10)
        self.assertEqual(cq.percentile([7], 95), 7)
        self.assertEqual(cq.percentile([], 95), 0)


class TestLabels(unittest.TestCase):
    def setUp(self):
        self.pools = cq.load_pools((ROOT / "infra" / "arc.yaml").read_text())

    def test_pools_loaded_from_arc_yaml(self):
        # Fuente única: los runnerScaleSetName de infra/arc.yaml, no copiados.
        self.assertIn("arc-k8s", self.pools)
        self.assertIn("arc-openclaw", self.pools)
        self.assertIn("x86-hermes", self.pools)  # extra declarado

    def test_classification(self):
        cases = {
            "arc-k8s": "pool", "arc-openclaw": "pool", "x86-hermes": "pool",
            "ubuntu-latest": "github", "ubuntu-24.04": "github",
            "macos-14": "github", "windows-2022": "github",
            "ubuntu-latest-32-core": "sin-pool",  # el caso del spec
            "ubuntu-24.04-96-core": "sin-pool", "blacksmith-4vcpu-ubuntu-2404": "sin-pool",
            "label-que-no-existe": "sin-pool",
        }
        for label, want in cases.items():
            self.assertEqual(cq.classify_label(label, self.pools), want, label)


class TestCollect(unittest.TestCase):
    def setUp(self):
        self.jobs = cq.collect_jobs(fixture_client(), ORG, SINCE, NOW)

    def test_fixtures_cover_three_repos(self):
        self.assertEqual({j.repo for j in self.jobs},
                         {"skirmshop-labels", "hermes-agent", "k8s-gitops-pocharlies"})

    def test_percentiles_fixed(self):
        # Cifras del fixture fijo (no de la API viva): si suben al re-capturar,
        # este test avisa.
        waits = [j.wait for j in self.jobs]
        self.assertEqual(cq.percentile(waits, 50), 3)
        self.assertEqual(cq.percentile(waits, 95), 1022)
        # 86401 s: job con label sin runner real (ubuntu-latest-32-core) que
        # esperó las 24 h de timeout — el arranque fantasma de la API.
        self.assertEqual(max(waits), 86401)

    def test_32_core_jobs_present_and_sin_pool(self):
        sin = [j for j in self.jobs
               if cq.classify_label(j.label, self.pools_for_test()) == "sin-pool"]
        self.assertTrue(any(j.repo == "hermes-agent" and "32-core" in j.label
                            for j in sin))

    def pools_for_test(self):
        return cq.load_pools((ROOT / "infra" / "arc.yaml").read_text())


class TestQueuedAge(unittest.TestCase):
    def test_queued_job_counts_age_to_now(self):
        created = (NOW - dt.timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        runs = {"workflow_runs": [{"id": 1, "run_number": 1, "name": "ci",
                                   "run_attempt": 1, "event": "push",
                                   "head_branch": "main", "created_at": created,
                                   "status": "queued", "conclusion": None}]}
        jobs = {"jobs": [{"name": "j", "labels": ["arc-k8s"], "status": "queued",
                          "conclusion": None, "created_at": created,
                          "started_at": None, "completed_at": None}]}

        def transport(url, headers):
            if url.endswith("/jobs?per_page=100"):
                return 200, {}, json.dumps(jobs).encode()
            if "/actions/runs" in url:
                return 200, {}, json.dumps(runs).encode()
            raise AssertionError(url)

        got = cq.collect_jobs(cq.Client(token="t", transport=transport), ORG,
                              SINCE, NOW, now=NOW, repos=["r"])
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0].queued_now)
        self.assertEqual(got[0].wait, 1800)  # edad hasta `now`, criterio del spec


class TestExactMode(unittest.TestCase):
    """El atajo de `run_started_at` es aproximación: los asserts van exactos."""

    def _transport(self):
        run = {"workflow_runs": [{"id": 1, "run_number": 1, "name": "ci",
                                  "run_attempt": 1, "event": "push",
                                  "head_branch": "main",
                                  "created_at": "2026-10-01T10:00:00Z",
                                  "run_started_at": "2026-10-01T10:00:02Z",
                                  "updated_at": "2026-10-01T10:20:00Z",
                                  "status": "completed", "conclusion": "success"}]}
        jobs = {"jobs": [{"name": "lento", "labels": ["arc-k8s"],
                          "status": "completed", "conclusion": "success",
                          "created_at": "2026-10-01T10:00:02Z",
                          "started_at": "2026-10-01T10:05:02Z",
                          "completed_at": "2026-10-01T10:10:00Z"}]}

        def transport(url, headers):
            if url.endswith("/jobs?per_page=100"):
                return 200, {}, json.dumps(jobs).encode()
            return 200, {}, json.dumps(run).encode()
        return transport

    def test_exact_measures_job_level(self):
        # run «rápido» (2 s a nivel de run) con un job que esperó 300 s:
        # exact=True debe dar 300; el atajo daría 2.
        for exact, want in ((True, 300), (False, 2)):
            got = cq.collect_jobs(
                cq.Client(token="t", transport=self._transport()), ORG,
                SINCE, NOW, now=NOW, repos=["r"], exact=exact)
            self.assertEqual(len(got), 1)
            self.assertEqual(got[0].wait, want, f"exact={exact}")


class TestRerunFloor(unittest.TestCase):
    def test_rerun_uses_job_level_only(self):
        # Caso del fixture (hermes-agent#4, intento 2): «Detect affected areas»
        # arrastra un started_at de un intento anterior (8 h antes de su
        # created). Usarlo como suelo sobreestima (así se midió mal
        # skirmshop-labels#151: 1189 s cuando a mano eran 96 s). Con la regla
        # corregida: 0 s ese job y 70 s el fantasma, sin suelo.
        jobs = cq.collect_jobs(fixture_client(), ORG, SINCE, NOW)
        got = {j.name: j.wait for j in jobs
               if j.repo == "hermes-agent" and j.run_number == 4}
        self.assertEqual(got, {"Detect affected areas": 0,
                               "nix flake check": 70})

    def test_floor_only_for_jobs_that_existed_in_the_queue(self):
        # run en cola 600 s (intento 1): el job que ya existía cuenta 600; el
        # creado después del arranque (needs) conserva su espera propia (30).
        run = {"workflow_runs": [{"id": 1, "run_number": 1, "name": "ci",
                                  "run_attempt": 1, "event": "push",
                                  "head_branch": "main",
                                  "created_at": "2026-10-01T10:00:00Z",
                                  "run_started_at": "2026-10-01T10:10:00Z",
                                  "updated_at": "2026-10-01T10:30:00Z",
                                  "status": "completed", "conclusion": "success"}]}
        jobs = {"jobs": [
            {"name": "primero", "labels": ["arc-k8s"], "status": "completed",
             "conclusion": "success", "created_at": "2026-10-01T10:00:01Z",
             "started_at": "2026-10-01T10:10:00Z",
             "completed_at": "2026-10-01T10:20:00Z"},
            {"name": "needs", "labels": ["arc-k8s"], "status": "completed",
             "conclusion": "success", "created_at": "2026-10-01T10:20:00Z",
             "started_at": "2026-10-01T10:20:30Z",
             "completed_at": "2026-10-01T10:30:00Z"}]}

        def transport(url, headers):
            if url.endswith("/jobs?per_page=100"):
                return 200, {}, json.dumps(jobs).encode()
            return 200, {}, json.dumps(run).encode()

        got = cq.collect_jobs(cq.Client(token="t", transport=transport), ORG,
                              SINCE, NOW, now=NOW, repos=["r"])
        self.assertEqual({j.name: j.wait for j in got},
                         {"primero": 600, "needs": 30})


class TestCancelled(unittest.TestCase):
    def test_rule_concurrency(self):
        old = job(conclusion="cancelled", started_at=None,
                  created_at=dt.datetime(2026, 10, 1, 10, tzinfo=dt.timezone.utc))
        newer = job(run_number=2, created_at=dt.datetime(2026, 10, 1, 11,
                                                        tzinfo=dt.timezone.utc))
        causa = cq.classify_cancelled(old, cq.runs_index([old, newer]))
        self.assertTrue(causa.startswith("usuario: reemplazado"))

    def test_rule_queued_cancel(self):
        j = job(conclusion="cancelled", started_at=None, completed_at=NOW)
        self.assertEqual(cq.classify_cancelled(j, {}), "usuario: cancelado en cola")

    def test_rule_infra_inflight(self):
        j = job(conclusion="cancelled",
                started_at=NOW - dt.timedelta(minutes=5), completed_at=NOW)
        self.assertEqual(cq.classify_cancelled(j, {}),
                         "infra: cancelado durante ejecución")

    def test_rule_sin_runner_timeout(self):
        # arranque fantasma de la API: started==created y muere tras 24 h
        # esperando un runner inexistente → infra, no «cancelado en cola».
        j = job(repo="hermes-agent", labels=("ubuntu-latest-32-core",),
                conclusion="cancelled", started_at=NOW - dt.timedelta(hours=24),
                completed_at=NOW, status="completed", wait=86400)
        j.created_at = j.started_at
        pools = frozenset({"arc-k8s"})
        self.assertTrue(j.never_ran)
        self.assertEqual(cq.classify_cancelled(j, {}, pools),
                         "infra: esperando un runner inexistente (label sin pool)")

    def test_fixture_cancellations_classified(self):
        jobs = cq.collect_jobs(fixture_client(), ORG, SINCE, NOW)
        cancelled = [j for j in jobs if j.conclusion == "cancelled"]
        self.assertTrue(cancelled, "el fixture debe traer cancelados")
        idx = cq.runs_index(jobs)
        for j in cancelled:
            self.assertTrue(cq.classify_cancelled(j, idx))


class TestClient(unittest.TestCase):
    def test_rate_limited_403_waits_and_retries(self):
        slept, calls = [], []

        def transport(url, headers):
            calls.append(url)
            if len(calls) == 1:
                return 403, {"X-RateLimit-Remaining": "0",
                             "X-RateLimit-Reset": "1000"}, b"{}"
            return 200, {}, b'{"ok": true}'

        c = cq.Client(token="t", transport=transport, sleep=slept.append)
        c._now = lambda: 900.0
        data, _, _ = c.get("/x")
        self.assertEqual(data, {"ok": True})
        self.assertEqual(slept, [101.0])

    def test_429_retry_after(self):
        calls = []

        def transport(url, headers):
            calls.append(url)
            if len(calls) == 1:
                return 429, {"Retry-After": "30"}, b"{}"
            return 200, {}, b'{}'

        c = cq.Client(token="t", transport=transport, sleep=lambda s: None)
        data, _, _ = c.get("/x")
        self.assertEqual(data, {})

    def test_403_forbidden_not_rate_limit(self):
        def transport(url, headers):
            return 403, {"X-RateLimit-Remaining": "123"}, b"{}"

        c = cq.Client(token="t", transport=transport)
        with self.assertRaises(cq.GitHubError):
            c.get("/x")

    def test_pagination_follows_link(self):
        def transport(url, headers):
            if "page=2" in url:
                return 200, {}, b'{"workflow_runs": [{"id": 2}]}'
            return 200, {"Link": f'<{cq.API}/p?per_page=1&page=2>; rel="next"'}, \
                b'{"workflow_runs": [{"id": 1}]}'

        c = cq.Client(token="t", transport=transport)
        ids = [r["id"] for r in c.paginate("/p", "workflow_runs", {"per_page": 1})]
        self.assertEqual(ids, [1, 2])

    def test_etag_304_returns_none(self):
        def transport(url, headers):
            assert headers.get("If-None-Match") == "abc"
            return 304, {}, b""

        c = cq.Client(token="t", transport=transport)
        data, _, _ = c.get("/x", etag="abc")
        self.assertIsNone(data)


class TestCli(unittest.TestCase):
    def _cli(self):
        spec = importlib.util.spec_from_file_location(
            "ci_queue_report", ROOT / "scripts" / "ci_queue_report.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_asserts_exit_codes(self):
        cli = self._cli()
        for asserts, want in ((["--assert-p95", "0"], 2),
                              (["--assert-p95", "999999", "--assert-max", "999999"], 0),
                              (["--assert-max", "0"], 2)):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli.main(["--org", ORG, "--since", cq.iso(SINCE),
                               "--hours", "168"] + asserts,
                              client=fixture_client(), now=NOW)
            self.assertEqual(rc, want, asserts)
            self.assertRegex(buf.getvalue(), r"p95=\d+ max=\d+")

    def test_report_sections(self):
        cli = self._cli()
        pools = cq.load_pools((ROOT / "infra" / "arc.yaml").read_text())
        jobs = cq.collect_jobs(fixture_client(), ORG, SINCE, NOW)
        report = cli.build_report(jobs, pools, SINCE, NOW, NOW)
        for section in ("## Espera por repo × label", "## sin-pool",
                        "## cancelados", "## ocupación por hora", "## Conclusiones"):
            self.assertIn(section, report)
        rows = [l for l in report.splitlines()
                if l.startswith("| ") and l.count("|") == 8
                and "repo" not in l.split("|")[1]]
        self.assertGreaterEqual(len(rows), 4, "filas repo×label del fixture")
        self.assertIn("ubuntu-latest-32-core", report)


class TestPeakConcurrency(unittest.TestCase):
    def test_overlap(self):
        t0 = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)
        js = [job(started_at=t0, completed_at=t0 + dt.timedelta(minutes=10)),
              job(started_at=t0 + dt.timedelta(minutes=5),
                  completed_at=t0 + dt.timedelta(minutes=15))]
        self.assertEqual(cq.peak_concurrency(js), 2)


if __name__ == "__main__":
    unittest.main()
