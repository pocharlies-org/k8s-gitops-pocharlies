#!/usr/bin/env python3
"""El informe separa pools y el assert no cuela un max malo del pool (INFRA-400, C5).

Fija como test de CI la medición real de las 48 h que qa midió a mano
(nota-sre-medicion-48h.md, id 29318, y 70-qa de INFRA-400): p95 56 s / max 303 s
SOLO en pool ARC, mientras el max global era 4608 s — cinco builds macOS/iOS
esperando al runner autoalojado único `macbook-nexus-app` (offline), fuera de
pool por la propia restricción del spec (los jobs macOS/Windows no se migran).
El fixture reproduce esa forma: 20 jobs de pool (p95 56, max 303) y 5 jobs
hosted (max 4608). Dos guardas:

1. el informe separa pools: la línea «Solo jobs de pool ARC» da 56/303 y la
   tabla marca el job hosted como `github`, no como pool;
2. el assert p95/max falla con exit 2 sobre el fixture — y si el job de 4608 s
   estuviera EN pool (sin la cobertura documentada de macOS), el max malo sale
   en la línea de pool y el assert sigue fallando: la separación de pools no es
   un agujero por el que colar un job de pool de 76 minutos sin nota.

Hermetic: fixtures JSON commiteados + transporte inyectable; nunca llama a
GitHub. Patrón unittest del repo (tests/test_ci_queue.py).
"""

import contextlib
import datetime as dt
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ci-queue"))
import ci_queue as cq  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ci-queue" / "medicion-48h"
ORG = "pocharlies-org"
NOW = dt.datetime(2026, 10, 31, 12, 0, 0, tzinfo=dt.timezone.utc)
SINCE = NOW - dt.timedelta(hours=48)
POOLS_TXT = (ROOT / "infra" / "arc.yaml").read_text()


def fixture_transport():
    """Mismo patrón que tests/test_ci_queue.py: fixtures por path, sin red."""
    def transport(url, headers):
        path = url.split("?")[0].replace(cq.API, "")
        params = dict(p.split("=", 1) for p in url.split("?", 1)[1:]
                      for p in [p]) if "?" in url else {}
        if path.endswith("/actions/runs"):
            name = (f"{params.get('repo', path.split('/')[3])}__"
                    + ("runs-queued.json" if params.get("status") == "queued"
                       else "runs.json"))
        elif path.endswith("/jobs"):
            parts = path.split("/")
            name = f"{parts[3]}__{parts[6]}__jobs.json"
        else:
            raise AssertionError(f"path sin fixture: {path}")
        f = FIXTURES / name
        if not f.exists():
            return 404, {}, b'{"message": "no fixture"}'
        return 200, {}, f.read_bytes()
    return transport


def fixture_client():
    return cq.Client(token="t", transport=fixture_transport())


def cli_module():
    spec = importlib.util.spec_from_file_location(
        "ci_queue_report", ROOT / "scripts" / "ci_queue_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def collect(repos=("repo-pool", "repo-mac")):
    return cq.collect_jobs(fixture_client(), ORG, SINCE, NOW, now=NOW,
                          repos=list(repos), exact=True)


def pool_line(report):
    return next(l for l in report.splitlines() if "Solo jobs de pool ARC" in l)


class ReportSeparaPools(unittest.TestCase):
    """C5 en el ámbito de la épica: las cifras del pool se leen separadas."""

    @classmethod
    def setUpClass(cls):
        cls.report = cli_module().build_report(
            collect(), cq.load_pools(POOLS_TXT), SINCE, NOW, NOW)

    def test_linea_de_pool_con_las_cifras_reales(self):
        # Medición del 31-10: p95 56 s y max 303 s SOLO en pool ARC.
        self.assertIn("p95 = 56 s · max = 303 s", pool_line(self.report))
        # El global lleva el max de los hosted: la separación es lo que hace
        # legible la decisión del tech-lead (C5 = pool ARC, INFRA-1056 el resto).
        self.assertIn("max = 4608 s", self.report.splitlines()[
            next(i for i, l in enumerate(self.report.splitlines())
                 if l.startswith("- p50"))])

    def test_tabla_tipo_por_label(self):
        rows = [l for l in self.report.splitlines() if l.startswith("| repo-")]
        self.assertTrue(any("| repo-pool | arc-k8s | pool |" in l for l in rows), rows)
        self.assertTrue(any("| repo-mac | macos-15 | github |" in l for l in rows), rows)


class AssertsSobreFixture(unittest.TestCase):
    """`--assert-p95/--assert-max` sobre el fixture de la medición real."""

    def _main(self, argv):
        err = io.StringIO()
        out = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            rc = cli_module().main(
                ["--org", ORG, "--repo", "repo-pool", "--repo", "repo-mac",
                 "--since", cq.iso(SINCE), "--hours", "48"] + argv,
                client=fixture_client(), now=NOW)
        return rc, out.getvalue(), err.getvalue()

    def test_max_global_4608_falla_con_exit_2(self):
        # La orden que lanzó la medición real (--assert-p95 600 --assert-max 1800)
        # tuvo que fallar: max global 4608 > 1800. Así se documentó, no se coló.
        rc, out, err = self._main(["--assert-p95", "600", "--assert-max", "1800"])
        self.assertEqual(rc, 2)
        self.assertIn("ASSERT FALLADO", err)
        self.assertIn("max 4608 s > 1800 s", err)
        self.assertRegex(out, r"p95=\d+ max=4608")

    def test_umbrales_amplios_pasán(self):
        rc, out, err = self._main(["--assert-p95", "999999", "--assert-max", "999999"])
        self.assertEqual(rc, 0)


class MaxMaloEnPoolNoCuela(unittest.TestCase):
    """Sin la cobertura documentada de macOS, el 4608 es un job de pool: sale en
    la línea de pool y el assert falla. La separación no es un agujero."""

    def _client_pool(self):
        # Mismo fixture, jobs hosted re-etiquetados al pool (sin nota de cobertura).
        base = fixture_transport()

        def transport(url, headers):
            status, hdrs, body = base(url, headers)
            if url.endswith("/jobs?per_page=100") and "repo-mac" in url:
                page = json.loads(body)
                for j in page["jobs"]:
                    j["labels"] = ["arc-k8s"]
                return status, hdrs, json.dumps(page).encode()
            return status, hdrs, body

        return cq.Client(token="t", transport=transport)

    def test_max_malo_aparece_en_la_linea_de_pool(self):
        jobs = cq.collect_jobs(self._client_pool(), ORG, SINCE, NOW, now=NOW,
                               repos=["repo-pool", "repo-mac"], exact=True)
        report = cli_module().build_report(
            jobs, cq.load_pools(POOLS_TXT), SINCE, NOW, NOW)
        self.assertIn("max = 4608 s", pool_line(report))

    def test_assert_falla_con_el_max_dentro_del_pool(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = cli_module().main(
                ["--org", ORG, "--repo", "repo-pool", "--repo", "repo-mac",
                 "--since", cq.iso(SINCE), "--hours", "48", "--assert-max", "1800"],
                client=self._client_pool(), now=NOW)
        self.assertEqual(rc, 2)
        self.assertIn("max 4608 s > 1800 s", err.getvalue())


if __name__ == "__main__":
    unittest.main()
