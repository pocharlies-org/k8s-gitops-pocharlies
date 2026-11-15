"""INFRA-123: el perfil cps-a-sauvage no debe desalojar nunca hacia los cps.

Regresión guardada. El perfil `cps-a-sauvage` (LowNodeUtilization, pasada cada
2 min) desalojaba de cualquier nodo que cruzaba `targetThresholds` (cpu/mem 90).
Medido en vivo (logs del CronJob de kube-system, 15-11 10:56Z): la clasificación
es por REQUESTS y los cps están a 75-85% cpu — por debajo del 90 —, así que nunca
son fuente: el perfil jamás aliviaba los cps. Lo que hacía era desalojar de los
picos de atlantic/ubuntu; el scheduler repartía los pods desalojados y a las
09:36Z del 15-11 sentó affiliate-app (250m) en ks5-cp-1, que volvió a pasarse del
objetivo de capacidad (5776m y 5796m sobre 5525m; criterio C1 de INFRA-171).

Como el placement lo decide el scheduler y no el descheduler, la única palanca
efectiva es no desalojar: `targetThresholds` al techo (100) hace que ningún nodo
sea nunca "fuente" (el uso por requests no puede superar el 100% de allocatable).
El test falla si alguien baja targetThresholds y reactiva la consolidación sin
revisar la capacidad de los cps.
"""
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class DeschedulerNoConsolidationToCps(unittest.TestCase):
    def setUp(self):
        values = yaml.safe_load(
            (ROOT / "infra/descheduler/values.yaml").read_text(encoding="utf-8")
        )
        self.profiles = {
            profile["name"]: profile
            for profile in values["deschedulerPolicy"]["profiles"]
        }

    def test_cps_a_sauvage_target_thresholds_disable_consolidation(self):
        profile = self.profiles["cps-a-sauvage"]
        lnu = next(
            config for config in profile["pluginConfig"] if config["name"] == "LowNodeUtilization"
        )
        target = lnu["args"]["targetThresholds"]
        for resource in ("cpu", "memory"):
            self.assertGreaterEqual(
                target[resource],
                100,
                "INFRA-123: targetThresholds por debajo de 100 reactiva la consolidación "
                "de LowNodeUtilization, que vierte picos de atlantic/ubuntu sobre los cps "
                "vía el scheduler y vuelve a pasarse del objetivo de capacidad (C1).",
            )


if __name__ == "__main__":
    unittest.main()
