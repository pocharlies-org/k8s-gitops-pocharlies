"""SC-2495: el planificador de AlphaLink se despliega desde su propio repo de
producto (patrón fichajes-alphalink), en el namespace del cliente."""
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps/horarios-alphalink.yaml"


class HorariosAlphalinkApplicationTest(unittest.TestCase):
    def setUp(self):
        self.app = yaml.safe_load(APP.read_text(encoding="utf-8"))
        self.spec = self.app["spec"]

    def test_apunta_al_repo_del_producto(self):
        self.assertEqual(self.app["metadata"]["name"], "horarios-alphalink")
        self.assertEqual(self.spec["source"]["repoURL"],
                         "https://github.com/pocharlies-org/horarios-alphalink")
        self.assertEqual(self.spec["source"]["path"], "k8s")
        self.assertEqual(self.spec["source"]["targetRevision"], "main")

    def test_vive_en_el_namespace_de_alphalink(self):
        # Los CronJobs de fichajes ya viven ahí: el producto del cliente, un ns.
        self.assertEqual(self.spec["destination"]["namespace"], "alphalink")

    def test_esta_declarado_en_el_kustomization(self):
        res = yaml.safe_load((ROOT / "kustomization.yaml").read_text(encoding="utf-8"))["resources"]
        self.assertIn("apps/horarios-alphalink.yaml", res)


if __name__ == "__main__":
    unittest.main()
