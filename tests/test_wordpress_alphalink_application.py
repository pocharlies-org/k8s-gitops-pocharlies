"""SC-2659: la web pública de AlphaLink (WordPress) se despliega desde su repo
de producto, en el namespace del cliente."""
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps/wordpress-alphalink.yaml"


class WordpressAlphalinkApplicationTest(unittest.TestCase):
    def setUp(self):
        self.app = yaml.safe_load(APP.read_text(encoding="utf-8"))
        self.spec = self.app["spec"]

    def test_apunta_al_repo_del_producto(self):
        self.assertEqual(self.app["metadata"]["name"], "wordpress-alphalink")
        self.assertEqual(self.spec["source"]["repoURL"],
                         "https://github.com/pocharlies-org/wordpress-alphalink")
        self.assertEqual(self.spec["source"]["path"], "k8s")
        self.assertEqual(self.spec["source"]["targetRevision"], "main")

    def test_vive_en_el_namespace_de_alphalink(self):
        # Todo lo del cliente en un ns (fichajes, horarios y la web).
        self.assertEqual(self.spec["destination"]["namespace"], "alphalink")

    def test_esta_declarado_en_el_kustomization(self):
        res = yaml.safe_load((ROOT / "kustomization.yaml").read_text(encoding="utf-8"))["resources"]
        self.assertIn("apps/wordpress-alphalink.yaml", res)


if __name__ == "__main__":
    unittest.main()
