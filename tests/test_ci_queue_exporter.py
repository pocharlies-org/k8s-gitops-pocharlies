#!/usr/bin/env python3
"""Tests del exporter de cola CI (INFRA-550). Hermetic: API simulada con los
fixtures de P1 y transportes inyectables; nunca llama a GitHub."""

import datetime as dt
import json
import sys
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


def dict_transport(pages: dict, calls: list, headers_seen: list | None = None):
    """Transporte de prueba: `pages` mapea substring de path → (status, dict|bytes, hdrs)."""
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


class EmptyQueueTest(unittest.TestCase):
    """Cola vacía con los fixtures reales de P1 (repos.json + runs-queued.json)."""

    def test_scrape(self):
        calls = []
        client = client_with(fixture_transport(calls))
        result = exporter.scrape(client, POOLS, {}, NOW)
        self.assertEqual(result["queued"], {})
        self.assertEqual(result["oldest"], {})
        self.assertEqual(result["errors"], 0)
        out = exporter.render(result, ts_success=123.0, rate_remaining=4900, errors_total=0)
        self.assertIn("ci_queue_scrape_success_timestamp_seconds 123", out)
        self.assertIn("ci_queue_api_rate_remaining 4900", out)
        self.assertIn("ci_queue_errors_total 0", out)


class QueuedJobsTest(unittest.TestCase):
    """Cola viva: label sin pool, label de pool, job ya arrancado y completado."""

    PAGES = {
        "/orgs/pocharlies-org/repos": (200, [
            {"name": "repo-x", "archived": False, "pushed_at": "2026-10-04T00:00:00Z"},
            {"name": "repo-viejo", "archived": False, "pushed_at": "2026-01-01T00:00:00Z"},
            {"name": "repo-arch", "archived": True, "pushed_at": "2026-10-04T00:00:00Z"},
        ], {}),
        # la clave lleva `?` para no comerse también la URL de jobs
        "repo-x/actions/runs?": (200, {"workflow_runs": [
            {"id": 1, "status": "queued", "created_at": "2026-10-05T11:00:00Z"},
        ]}, {}),
        "runs/1/jobs": (200, {"jobs": [
            {"status": "queued", "created_at": "2026-10-05T11:30:00Z",
             "labels": ["ubuntu-latest-32-core"]},
            {"status": "queued", "created_at": "2026-10-05T11:50:00Z",
             "labels": ["arc-k8s"]},
            {"status": "in_progress", "started_at": "2026-10-05T11:55:00Z",
             "created_at": "2026-10-05T11:00:00Z", "labels": ["arc-k8s"]},
            {"status": "completed", "created_at": "2026-10-05T10:00:00Z",
             "started_at": "2026-10-05T10:01:00Z", "labels": ["arc-k8s"]},
        ]}, {}),
    }

    def test_scrape(self):
        calls = []
        result = exporter.scrape(client_with(self.dict_t()), POOLS, {}, NOW)
        self.assertEqual(result["queued"],
                         {("ubuntu-latest-32-core", "sin-pool"): 1, ("arc-k8s", "pool"): 1})
        self.assertEqual(result["oldest"],
                         {("ubuntu-latest-32-core", "sin-pool", "repo-x"): 1800.0,
                          ("arc-k8s", "pool", "repo-x"): 600.0})
        self.assertEqual(result["errors"], 0)
        # repo-viejo (sin push en 7 días) y repo-arch no se preguntan
        self.assertFalse(any("repo-viejo" in c or "repo-arch" in c for c in calls))

    def dict_t(self):
        return dict_transport(self.PAGES, [])


class EtagTest(unittest.TestCase):
    """304: el ciclo repite métricas sin volver a pedir los jobs."""

    def test_304_reuses_cache(self):
        runs = {"workflow_runs": [{"id": 1, "status": "queued"}]}
        jobs = {"jobs": [{"status": "queued", "created_at": "2026-10-05T11:45:00Z",
                          "labels": ["arc-k8s"]}]}
        calls = []

        def transport(url, headers):
            calls.append(url)
            if "/orgs/" in url:
                return 200, {}, json.dumps([{"name": "repo-x", "archived": False,
                                         "pushed_at": "2026-10-04T00:00:00Z"}]).encode()
            if "/actions/runs" in url:
                if headers.get("If-None-Match") == '"E1"':
                    return 304, b"", {}
                return 200, {"ETag": '"E1"'}, json.dumps(runs).encode()
            if url.endswith("/jobs"):
                return 200, {}, json.dumps(jobs).encode()
            raise AssertionError(url)

        cache = {}
        first = exporter.scrape(client_with(transport), POOLS, cache, NOW)
        calls.clear()
        second = exporter.scrape(client_with(transport), POOLS, cache, NOW)
        self.assertEqual(first, second)
        # segundo ciclo: runs pedido con ETag → 304 → la API de jobs no se repite
        self.assertFalse(any(url.endswith("/jobs") for url in calls))


class RateLimitAndErrorsTest(unittest.TestCase):
    def test_repo_rate_limited_counts_error_and_keeps_others(self):
        pages = {
            "/orgs/pocharlies-org/repos": (200, [
                {"name": "repo-x", "archived": False, "pushed_at": "2026-10-04T00:00:00Z"},
                {"name": "repo-y", "archived": False, "pushed_at": "2026-10-04T00:00:00Z"},
            ], {}),
            "repo-x/actions/runs?": (200, {"workflow_runs": [
                {"id": 1, "status": "queued"}]}, {}),
            "runs/1/jobs": (200, {"jobs": [{"status": "queued",
                                           "created_at": "2026-10-05T11:00:00Z",
                                           "labels": ["arc-k8s"]}]}, {}),
            # repo-y: 403 de cuota, dos intentos → GitHubError
            "repo-y/actions/runs?": (403, {}, {"x-ratelimit-remaining": "0",
                                              "x-ratelimit-reset": "1"}),
        }
        result = exporter.scrape(client_with(dict_transport(pages, [])), POOLS, {}, NOW)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["queued"], {("arc-k8s", "pool"): 1})  # repo-x sigue

    def test_job_sin_created_at_no_mata(self):
        pages = {
            "/orgs/pocharlies-org/repos": (200, [
                {"name": "repo-x", "archived": False, "pushed_at": "2026-10-04T00:00:00Z"}], {}),
            "repo-x/actions/runs?": (200, {"workflow_runs": [
                {"id": 1, "status": "queued"}]}, {}),
            "runs/1/jobs": (200, {"jobs": [{"status": "queued", "labels": ["arc-k8s"]}]}, {}),
        }
        result = exporter.scrape(client_with(dict_transport(pages, [])), POOLS, {}, NOW)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["queued"], {})


if __name__ == "__main__":
    unittest.main()
