"""DGX-1165: LowNodeUtilization nunca debe desalojar pods de control-nexus.

Regresión guardada: el perfil `cps-a-sauvage` (LowNodeUtilization, pasada cada
2 min) expulsaba el worker de control-nexus en ping-pong (~30 pods/10 h, con
Redis timeouts desde sauvage). Arreglado en SC-2776 (PR #681, 29-10) excluyendo
el ns en `evictableNamespaces.exclude` de los args del plugin. En la API
v1alpha2 de v0.36.0 la opción vive en los args de LowNodeUtilization
(pkg/framework/plugins/nodeutilization/types.go), no en el DefaultEvictor: el
test falla si la exclusión se borra o se pone donde el descheduler la ignora.
"""
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class DeschedulerControlNexusExclusion(unittest.TestCase):
    def setUp(self):
        values = yaml.safe_load(
            (ROOT / "infra/descheduler/values.yaml").read_text(encoding="utf-8")
        )
        self.profiles = {
            profile["name"]: profile
            for profile in values["deschedulerPolicy"]["profiles"]
        }

    def test_low_node_utilization_profile_excludes_control_nexus(self):
        profile = self.profiles["cps-a-sauvage"]
        self.assertIn("LowNodeUtilization", profile["plugins"]["balance"]["enabled"])
        lnu = next(
            config for config in profile["pluginConfig"] if config["name"] == "LowNodeUtilization"
        )
        excluded = lnu["args"]["evictableNamespaces"]["exclude"]
        self.assertIn(
            "control-nexus",
            excluded,
            "DGX-1165: sin esta exclusión el descheduler vuelve a expulsar el worker "
            "de control-nexus cada 2 min (ping-pong, Redis timeouts desde sauvage)",
        )


if __name__ == "__main__":
    unittest.main()
