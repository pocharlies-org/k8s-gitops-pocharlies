#!/usr/bin/env python3
"""ci-queue/pools.txt es DERIVADO de infra/arc.yaml (fuente única, architect
§2): kustomize no puede montar ficheros fuera de su raíz, así que el exporter
monta una copia. Este test es la guarda de la derivación: si alguien añade o
renombra un pool (`runnerScaleSetName` o un label de `scaleSetLabels`,
INFRA-1437) en infra/arc.yaml sin regenerar pools.txt, falla aquí (patrón de
tests/test_arc_personal_namespaces.py)."""

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
        self.assertEqual(
            cq.load_pools(arc), cq.load_pools(pools_txt),
            msg="ci-queue/pools.txt no coincide con los pools de infra/arc.yaml. "
                "Regenerar desde la raíz del repo: python3 -c \"import sys; "
                "sys.path.insert(0,'ci-queue'); import ci_queue as cq; "
                "pools=sorted(cq.load_pools(open('infra/arc.yaml').read())); "
                "hdr=open('ci-queue/pools.txt').read().split(chr(10)*3)[0]+chr(10)*3; "
                "open('ci-queue/pools.txt','w').write(hdr+''.join("
                "'        runnerScaleSetName: '+p+chr(10) for p in pools))\"")


class LoadPoolsTest(unittest.TestCase):
    """load_pools ve los dos orígenes de pool de infra/arc.yaml (SC-6007):
    el nombre del scale set y las etiquetas extra de `scaleSetLabels`
    (INFRA-1437). Un label de scaleSetLabels ignorado = jobs reales clasificados
    `sin-pool` = CIQueueLabelWithoutPool falso positivo."""

    ARC = """
        runnerScaleSetName: arc-k8s
        scaleSetLabels:
          - arc-k8s
          - arc-k8s-light
        template:
          spec:
            tolerations:
              - key: dedicated
        runnerScaleSetName: arc-k8s-sauvage
        scaleSetLabels: [arc-k8s-light]
"""

    def test_block_and_inline_scale_set_labels(self):
        self.assertEqual(
            cq.load_pools(self.ARC),
            frozenset({"arc-k8s", "arc-k8s-light", "arc-k8s-sauvage"}))

    def test_items_de_otras_listas_no_son_pools(self):
        # `dedicated` es un item de tolerations, no un pool: solo se leen los
        # items que cuelgan de un `scaleSetLabels:`.
        self.assertNotIn("dedicated", cq.load_pools(self.ARC))

    def test_arc_k8s_light_es_pool(self):
        pools = cq.load_pools((ROOT / "infra" / "arc.yaml").read_text())
        self.assertIn("arc-k8s-light", pools)
        self.assertEqual(cq.classify_job(["arc-k8s-light"], pools),
                         ("arc-k8s-light", "pool"))


if __name__ == "__main__":
    unittest.main()
