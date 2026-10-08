#!/usr/bin/env python3
"""Tests del exporter de cola CI (INFRA-550). Hermetic: API simulada con los
fixtures de P1 y transportes inyectables; nunca llama a GitHub."""

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ci-queue"))
sys.path.insert(0, str(ROOT / "tests"))
import ci_queue as cq  # noqa: E402
import exporter  # noqa: E402
from test_ci_queue import fixture_transport  # noqa: E402

NOW = dt.datetime(2026, 10, 5, 12, 0, 0, tzinfo=dt.timezone.utc)
POOLS = cq.load_pools("runnerScaleSetName: arc-k8s\nrunnerScaleSetName: arc-openclaw\n")
ACTIVE = "2026-10-04T00:00:00Z"  # push dentro de los 7 días de NOW


def dict_transport(pages: dict, calls: list, headers_seen: list | None = None):
    """Transporte de prueba: `pages` mapea substring de URL → (status, body, hdrs).
    Gana la primera clave que case: las más específicas van antes."""
    def transport(url, headers):
        calls.append(url)
        if headers_seen is not None:
            headers_seen.append(dict(headers))
        for sub, (status, body, hdrs) in pages.items():
            if sub in url:
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                return status, hdrs, data
        raise AssertionError(f"URL no simulada: {url}")
    return transport


def client_with(transport):
    return cq.Client(token="t", transport=transport, sleep=lambda s: None)


def repos(*names, pushed=ACTIVE, archived=False):
    return [{"name": n, "archived": archived, "pushed_at": pushed} for n in names]


def job(status, created, started=None, labels=("arc-k8s",)):
    j = {"status": status, "created_at": created, "labels": list(labels)}
    if started:
        j["started_at"] = started
    return j


class EmptyQueueTest(unittest.TestCase):
    """Cola vacía con los fixtures reales de P1 (repos.json + runs-queued.json)."""

    def test_scrape(self):
        calls = []
        client = client_with(fixture_transport(calls))
        result = exporter.scrape(client, POOLS, {}, NOW)
        self.assertEqual(result["queued"], {})
        self.assertEqual(result["oldest"], {})
        self.assertEqual(result["errors"], 0)
        # no es vacío por no haber mirado: se pidió la lista de runs de cada repo
        for repo in ("hermes-agent", "k8s-gitops-pocharlies", "skirmshop-labels"):
            self.assertTrue(any(f"/repos/pocharlies-org/{repo}/actions/runs?" in c for c in calls), repo)
        out = exporter.render(result, ts_success=123.0, rate_remaining=4900, errors_total=0)
        self.assertIn("ci_queue_scrape_success_timestamp_seconds 123", out)
        self.assertIn("ci_queue_api_rate_remaining 4900", out)
        self.assertIn("ci_queue_errors_total 0", out)


class QueuedJobsTest(unittest.TestCase):
    """Cola viva. El discriminador es `status == queued`, no `started_at`."""

    PAGES = {
        "/orgs/pocharlies-org/repos": (200, repos("repo-x") + repos("repo-viejo", pushed="2026-01-01T00:00:00Z")
                                       + repos("repo-arch", archived=True), {}),
        # la clave lleva `?` para no comerse también la URL de jobs
        "repo-x/actions/runs?": (200, {"workflow_runs": [{"id": 1, "status": "queued"}]}, {}),
        "runs/1/jobs": (200, {"jobs": [
            job("queued", "2026-10-05T11:30:00Z", labels=("ubuntu-latest-32-core",)),
            job("queued", "2026-10-05T11:50:00Z"),
            # «arranque fantasma» de la API (started_at == created_at) en un job que
            # SIGUE en cola: tiene que contar (ci_queue.Job.never_ran)
            job("queued", "2026-10-05T11:40:00Z", started="2026-10-05T11:40:00Z",
                labels=("arc-openclaw",)),
            job("in_progress", "2026-10-05T11:00:00Z", started="2026-10-05T11:55:00Z"),
            job("completed", "2026-10-05T10:00:00Z", started="2026-10-05T10:01:00Z"),
            job("waiting", "2026-10-05T10:00:00Z"),  # esperando aprobación de un environment
        ]}, {}),
    }

    def test_scrape(self):
        calls = []
        result = exporter.scrape(client_with(dict_transport(self.PAGES, calls)), POOLS, {}, NOW)
        self.assertEqual(result["queued"], {("ubuntu-latest-32-core", "sin-pool"): 1,
                                            ("arc-k8s", "pool"): 1,
                                            ("arc-openclaw", "pool"): 1})
        self.assertEqual(result["oldest"], {("ubuntu-latest-32-core", "sin-pool", "repo-x"): 1800.0,
                                            ("arc-k8s", "pool", "repo-x"): 600.0,
                                            ("arc-openclaw", "pool", "repo-x"): 1200.0})
        self.assertEqual(result["errors"], 0)
        # repo-viejo (sin push en 7 días) y repo-arch (archivado) no se preguntan
        self.assertTrue(any("repo-x/actions/runs" in c for c in calls))
        self.assertFalse(any("repo-viejo" in c or "repo-arch" in c for c in calls))


class RenderEscapeTest(unittest.TestCase):
    """`label` es entrada externa (el `runs-on` de cualquier PR)."""

    def test_esc(self):
        self.assertEqual(exporter._esc('a"b\nc\\d'), 'a\\"b\\nc\\\\d')

    def test_label_con_inyeccion_da_una_linea_de_serie(self):
        evil = 'a"b\nci_queue_errors_total 0'
        pages = {
            "/orgs/pocharlies-org/repos": (200, repos("repo-x"), {}),
            "repo-x/actions/runs?": (200, {"workflow_runs": [{"id": 1}]}, {}),
            "runs/1/jobs": (200, {"jobs": [job("queued", "2026-10-05T11:00:00Z", labels=(evil,))]}, {}),
        }
        result = exporter.scrape(client_with(dict_transport(pages, [])), POOLS, {}, NOW)
        out = exporter.render(result, ts_success=1.0, rate_remaining=5, errors_total=7)
        lines = out.splitlines()
        series = [ln for ln in lines if ln.startswith("ci_queue_queued_jobs{")]
        age = [ln for ln in lines if ln.startswith("ci_queue_oldest_queued_job_age_seconds{")]
        self.assertEqual(len(series), 1)
        self.assertEqual(len(age), 1)
        # ninguna línea nace del texto inyectado, y el contador real sigue siendo 7
        self.assertEqual([ln for ln in lines if ln.startswith("ci_queue_errors_total")],
                         ["ci_queue_errors_total 7"])
        self.assertIn('label="a\\"b\\nci_queue_errors_total 0"', series[0])


class RunsListEtagTest(unittest.TestCase):
    """Con ETag la lista de runs en cola NO se vuelve a descargar (304 sin cuota);
    los jobs sí se piden otra vez, para que las edades se refresquen."""

    def test_304_revalidates_runs_list_and_refetches_jobs(self):
        calls, seen = [], []
        state = {"n": 0}

        def transport(url, headers):
            calls.append(url)
            seen.append((url, dict(headers)))
            if "/orgs/" in url:
                return 200, {}, json.dumps(repos("repo-x")).encode()
            if "/jobs" in url:  # antes que /actions/runs: la URL de jobs también lo contiene
                return 200, {}, json.dumps({"jobs": [job("queued", "2026-10-05T11:45:00Z")]}).encode()
            if "/actions/runs" in url:
                state["n"] += 1
                if headers.get("If-None-Match") == '"E1"':
                    return 304, {}, b""
                return 200, {"ETag": '"E1"'}, json.dumps({"workflow_runs": [{"id": 1}]}).encode()
            raise AssertionError(url)

        cache = {}
        first = exporter.scrape(client_with(transport), POOLS, cache, NOW)
        self.assertEqual(first["queued"], {("arc-k8s", "pool"): 1})  # no vacío: el test sí prueba algo
        seen.clear()
        second = exporter.scrape(client_with(transport), POOLS, cache, NOW)
        self.assertEqual(first, second)
        runs_req = [h for u, h in seen if "/actions/runs?" in u]
        self.assertEqual(len(runs_req), 1)
        self.assertEqual(runs_req[0].get("If-None-Match"), '"E1"')  # se revalidó y respondió 304
        self.assertTrue(any("/runs/1/jobs" in u for u, _ in seen))  # los jobs se vuelven a pedir


class RateLimitAndErrorsTest(unittest.TestCase):
    def test_repo_rate_limited_counts_error_and_keeps_others(self):
        pages = {
            "/orgs/pocharlies-org/repos": (200, repos("repo-x", "repo-y"), {}),
            "repo-x/actions/runs?": (200, {"workflow_runs": [{"id": 1}]}, {}),
            "runs/1/jobs": (200, {"jobs": [job("queued", "2026-10-05T11:00:00Z")]}, {}),
            # repo-y: 403 de cuota → GitHubError
            "repo-y/actions/runs?": (403, {}, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1"}),
        }
        result = exporter.scrape(client_with(dict_transport(pages, [])), POOLS, {}, NOW)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["queued"], {("arc-k8s", "pool"): 1})  # repo-x sigue

    def test_job_sin_created_at_no_mata(self):
        pages = {
            "/orgs/pocharlies-org/repos": (200, repos("repo-x"), {}),
            "repo-x/actions/runs?": (200, {"workflow_runs": [{"id": 1}]}, {}),
            "runs/1/jobs": (200, {"jobs": [{"status": "queued", "labels": ["arc-k8s"]}]}, {}),
        }
        result = exporter.scrape(client_with(dict_transport(pages, [])), POOLS, {}, NOW)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["queued"], {})

    def test_run_sin_id_y_repo_sin_name_no_matan_el_ciclo(self):
        # respuesta con forma rara en UN repo: error contado, el resto sigue
        pages = {
            "/orgs/pocharlies-org/repos": (200, [{"archived": False, "pushed_at": ACTIVE}]
                                           + repos("repo-x", "repo-y"), {}),
            "repo-x/actions/runs?": (200, {"workflow_runs": [{"status": "queued"}]}, {}),  # sin id
            "repo-y/actions/runs?": (200, {"workflow_runs": [{"id": 2}]}, {}),
            "runs/2/jobs": (200, {"jobs": [job("queued", "2026-10-05T11:00:00Z")]}, {}),
        }
        result = exporter.scrape(client_with(dict_transport(pages, [])), POOLS, {}, NOW)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["queued"], {("arc-k8s", "pool"): 1})


class RunCycleTest(unittest.TestCase):
    """El ciclo completo: cuota real en la métrica y ts_success solo con 0 errores."""

    @staticmethod
    def pages(repo_y_status=200):
        return {
            "/orgs/pocharlies-org/repos": (200, repos("repo-x", "repo-y"),
                                           {"X-RateLimit-Remaining": "4321"}),
            "repo-x/actions/runs?": (200, {"workflow_runs": [{"id": 1}]}, {"X-RateLimit-Remaining": "4320"}),
            "runs/1/jobs": (200, {"jobs": [job("queued", "2026-10-05T11:00:00Z")]},
                            {"X-RateLimit-Remaining": "4321"}),
            "repo-y/actions/runs?": (repo_y_status, {"workflow_runs": []},
                                     {"X-RateLimit-Remaining": "4321"} if repo_y_status == 200
                                     else {"x-ratelimit-remaining": "9", "x-ratelimit-reset": "1"}),
        }

    def client(self, pages, state, tmp):
        token = Path(tmp) / "token"
        token.write_text("ghs_fake\n")
        http = dict_transport(pages, [])
        return client_with(exporter.make_transport(str(token), stats=state,
                                                   http=lambda u, h: http(u, h)))

    def test_rate_remaining_llega_a_la_metrica_y_ts_avanza(self):
        state = {"rate_remaining": 0, "ts_success": 0.0, "errors_total": 0}
        with tempfile.TemporaryDirectory() as tmp:
            out = exporter.run_cycle(self.client(self.pages(), state, tmp), POOLS, {}, state, NOW)
        self.assertIn("ci_queue_api_rate_remaining 4321", out)
        self.assertIn(f"ci_queue_scrape_success_timestamp_seconds {NOW.timestamp():.0f}", out)
        self.assertIn("ci_queue_errors_total 0", out)

    def test_ciclo_con_errores_no_avanza_ts_success(self):
        state = {"rate_remaining": 0, "ts_success": 100.0, "errors_total": 0}
        with tempfile.TemporaryDirectory() as tmp:
            out = exporter.run_cycle(self.client(self.pages(repo_y_status=403), state, tmp),
                                     POOLS, {}, state, NOW)
        self.assertIn("ci_queue_scrape_success_timestamp_seconds 100\n", out)  # sigue el anterior
        self.assertIn("ci_queue_errors_total 1", out)
        self.assertEqual(state["ts_success"], 100.0)
        self.assertEqual(state["errors_total"], 1)

    def test_token_se_lee_en_cada_request(self):
        # ESO renueva el Secret cada 30 min: un token leído una vez caducaría
        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            token = Path(tmp) / "token"
            transport = exporter.make_transport(
                str(token), http=lambda u, h: (seen.append(h["Authorization"]) or (200, {}, b"{}")))
            token.write_text("uno")
            transport("https://x/a", {})
            token.write_text("dos")
            transport("https://x/b", {})
        self.assertEqual(seen, ["Bearer uno", "Bearer dos"])


if __name__ == "__main__":
    unittest.main()
