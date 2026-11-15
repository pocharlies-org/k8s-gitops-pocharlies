"""2026-11-15: atlantic tiene un tope de 8 runners de arc-k8s.

Con el pool lleno (32/32) atlantic (16 CPU, tambien aloja paseo-0) llego a ~23
runners de arc-k8s: 16 CPU al 99 % y el daemon de Paseo sin CPU. El pool de
`runs-on: arc-k8s` se parte en dos scale sets que comparten esa etiqueta
(`scaleSetLabels: [arc-k8s]` -> `spec.runnerScaleSetLabels`, chart 0.14.1):

  - arc-k8s          maxRunners 24, atlantic excluido (required NotIn por
                     hostname), sauvage preferido, x86 de desborde;
  - arc-k8s-atlantic maxRunners 8, fijado a atlantic.

24 + 8 = 32: la capacidad total no cambia. Este test es la puerta de esa
division; el render real con helm lo comprueba scripts/verify_arc_runner_render.sh.
"""

from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATED_COMMENT = re.compile(r"#\s*\d{4}-\d{2}-\d{2}\s+\S+")
EDGE_TOLERATION = {
    "effect": "NoSchedule",
    "key": "role",
    "operator": "Equal",
    "value": "edge",
}


def arc_application(name: str) -> dict:
    documents = yaml.safe_load_all(
        (ROOT / "infra/arc.yaml").read_text(encoding="utf-8")
    )
    for document in documents:
        if (
            isinstance(document, dict)
            and document.get("kind") == "Application"
            and document["metadata"]["name"] == name
        ):
            return document
    raise AssertionError(f"Application {name} not found in infra/arc.yaml")


def arc_values(name: str) -> dict:
    return yaml.safe_load(
        arc_application(name)["spec"]["source"]["helm"]["values"]
    )


class ArcAtlanticCapTest(unittest.TestCase):
    def setUp(self) -> None:
        self.shared = arc_values("arc-k8s")
        self.atlantic = arc_values("arc-k8s-atlantic")
        self.shared_spec = self.shared["template"]["spec"]
        self.atlantic_spec = self.atlantic["template"]["spec"]

    def test_atlantic_scale_set_serves_the_arc_k8s_label(self) -> None:
        """Mismo `runs-on: arc-k8s`: el scale set de atlantic lleva la etiqueta
        explicita y arc-k8s no declara ninguna (su etiqueta es su nombre)."""
        self.assertEqual(self.atlantic["runnerScaleSetName"], "arc-k8s-atlantic")
        self.assertEqual(self.atlantic["scaleSetLabels"], ["arc-k8s"])
        self.assertEqual(self.shared["runnerScaleSetName"], "arc-k8s")
        self.assertNotIn("scaleSetLabels", self.shared)

    def test_same_org_secret_and_controller(self) -> None:
        for key in ("githubConfigUrl", "githubConfigSecret", "controllerServiceAccount"):
            self.assertEqual(self.atlantic[key], self.shared[key], key)
        self.assertEqual(
            arc_application("arc-k8s-atlantic")["spec"]["destination"],
            arc_application("arc-k8s")["spec"]["destination"],
        )

    def test_total_capacity_stays_thirty_two(self) -> None:
        self.assertEqual(self.shared["maxRunners"], 24)
        self.assertEqual(self.atlantic["maxRunners"], 8)
        self.assertEqual(self.shared["maxRunners"] + self.atlantic["maxRunners"], 32)

    def test_atlantic_set_has_no_warm_runners(self) -> None:
        """Los 2 runners calientes (INFRA-334) los pone arc-k8s."""
        self.assertEqual(self.atlantic["minRunners"], 0)
        self.assertEqual(self.shared["minRunners"], 2)

    def test_atlantic_set_is_pinned_to_atlantic_only(self) -> None:
        self.assertEqual(
            self.atlantic_spec["nodeSelector"],
            {"kubernetes.io/arch": "amd64", "kubernetes.io/hostname": "atlantic"},
        )
        self.assertNotIn(EDGE_TOLERATION, self.atlantic_spec["tolerations"])

    def test_shared_set_excludes_atlantic_and_prefers_sauvage(self) -> None:
        node_affinity = self.shared_spec["affinity"]["nodeAffinity"]
        required = node_affinity["requiredDuringSchedulingIgnoredDuringExecution"]
        expressions = required["nodeSelectorTerms"][0]["matchExpressions"]
        self.assertIn(
            {"key": "kubernetes.io/hostname", "operator": "NotIn", "values": ["atlantic", "ubuntu"]},  # SC-5633: tampoco el x86
            expressions,
        )
        self.assertIn(
            {"key": "node-role.kubernetes.io/control-plane", "operator": "DoesNotExist"},
            expressions,
        )
        preferred = node_affinity["preferredDuringSchedulingIgnoredDuringExecution"]
        self.assertEqual(
            preferred,
            [
                {
                    "weight": 100,
                    "preference": {
                        "matchExpressions": [
                            {
                                "key": "kubernetes.io/hostname",
                                "operator": "In",
                                "values": ["sauvage"],
                            }
                        ]
                    },
                }
            ],
        )
        self.assertIn(EDGE_TOLERATION, self.shared_spec["tolerations"])
        # el nodeSelector de arc-k8s no fija hostname: x86 sigue de desborde
        self.assertNotIn("kubernetes.io/hostname", self.shared_spec["nodeSelector"])

    def test_pod_template_is_the_same_apart_from_placement(self) -> None:
        """DinD, limites, MTU, sidecar y volumenes: un solo template en dos
        sitios; si uno cambia, cambia el otro."""
        for key in ("initContainers", "containers", "volumes"):
            self.assertEqual(self.atlantic_spec[key], self.shared_spec[key], key)

    def test_atlantic_cap_carries_a_dated_comment(self) -> None:
        """Como arc-k8s: el bloque de comentarios justo encima de maxRunners
        lleva fecha y la razon del numero."""
        values_text = arc_application("arc-k8s-atlantic")["spec"]["source"]["helm"]["values"]
        lines = values_text.splitlines()
        index = next(
            i for i, line in enumerate(lines) if re.match(r"\s*maxRunners:", line)
        )
        block = []
        for offset in range(1, index + 1):
            line = lines[index - offset].strip()
            if not line.startswith("#"):
                break
            block.append(line)
        joined = "\n".join(block)
        self.assertRegex(joined, DATED_COMMENT)
        self.assertIn("paseo-0", joined)
        self.assertIn("24 + 8 = 32", joined)


if __name__ == "__main__":
    unittest.main()
