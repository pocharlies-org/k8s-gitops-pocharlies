#!/usr/bin/env python3
"""ci-queue/pools.txt es DERIVADO de infra/arc.yaml (fuente única, architect
§2): kustomize no puede montar ficheros fuera de su raíz, así que el exporter
monta una copia. Este test es la guarda de la derivación: si alguien añade o
renombra un `runnerScaleSetName` en infra/arc.yaml sin regenerar pools.txt,
falla aquí (patrón de tests/test_arc_personal_namespaces.py)."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ci-queue"))
import ci_queue as cq  # noqa: E402


class PoolsDerivationTest(unittest.TestCase):
    def test_pools_txt_matches_arc_yaml(self):
        arc = (ROOT / "infra" / "arc.yaml").read_text()
        pools_txt = (ROOT / "ci-queue" / "pools.txt").read_text()
        self.assertEqual(cq.load_pools(arc), cq.load_pools(pools_txt))


if __name__ == "__main__":
    unittest.main()
