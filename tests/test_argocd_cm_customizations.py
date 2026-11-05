import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

# Una clave de ConfigMap solo admite [-._a-zA-Z0-9]: el apply del argocd-cm con otra
# cosa (p. ej. la `/` de batch/CronJob) lo rechaza la API y tumba el sync de la app
# `argocd`. ArgoCD espera `<group>_<Kind>` (como `apps_ReplicaSet` del cm vivo).
CM_KEY = re.compile(r"^[-._a-zA-Z0-9]+$")


class ArgocdCmCustomizationsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        values = yaml.safe_load((ROOT / "argocd/values.yaml").read_text())
        cls.cm = values["configs"]["cm"]

    def test_every_customization_key_is_a_valid_configmap_key(self) -> None:
        keys = [k for k in self.cm if k.startswith("resource.customizations.")]
        self.assertTrue(keys, "no resource.customizations.* keys found")
        for key in keys:
            self.assertRegex(key, CM_KEY, f"invalid ConfigMap key: {key!r}")

    def test_cronjob_health_is_healthy_under_group_underscore_kind(self) -> None:
        key = "resource.customizations.health.batch_CronJob"
        self.assertIn(key, self.cm)
        self.assertIn("status = 'Healthy'", self.cm[key])
        self.assertNotIn("resource.customizations.health.batch/CronJob", self.cm)

    def test_every_health_script_returns_its_table(self) -> None:
        # SC-2082: sin `return` el script da nil, ArgoCD lo lee como un health vacio (ni
        # Healthy ni Degraded) y el sync multi-paso espera "healthy state of" para siempre.
        keys = [k for k in self.cm if k.startswith("resource.customizations.health.")]
        self.assertTrue(keys, "no resource.customizations.health.* keys found")
        for key in keys:
            lines = [ln.strip() for ln in self.cm[key].splitlines() if ln.strip()]
            self.assertRegex(lines[-1], r"^return\s+\w+$", f"{key} must end in `return <table>`")


if __name__ == "__main__":
    unittest.main()
