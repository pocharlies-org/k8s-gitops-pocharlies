"""2026-11-16 (INFRA-1397): sauvage tiene un tope de 3 runners de arc-k8s.

El md3 de sauvage es un HDD (RAID sda/sdb). Con 24 runners de arc-k8s
arrancando en frio a la vez (re-admision de #765, 2026-11-15) pasó de ~30 % a
100 % de utilizacion y el iowait de 1 % a 26-31 % en 10 min; skirmshop y minio
comparten ese disco. Daniel fijo el limite en 3 runners. arc-k8s sigue SIN
tolerar role=edge (el taint de sauvage): el unico camino a sauvage es este
scale set, que comparte la etiqueta `arc-k8s` (`scaleSetLabels: [arc-k8s]` ->
`spec.runnerScaleSetLabels`, chart 0.14.1) y por tanto casa el mismo
`runs-on: arc-k8s`. 21 (arc-k8s, x86) + 8 (atlantic) + 3 (sauvage) = 32.

Este test es la puerta de esa division; el render real con helm lo comprueba
scripts/verify_arc_runner_render.sh.
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
POOL_DEV_TOLERATION = {
    "effect": "PreferNoSchedule",
    "key": "pool",
    "operator": "Equal",
    "value": "dev",
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


class ArcSauvageCapTest(unittest.TestCase):
    def setUp(self) -> None:
        self.shared = arc_values("arc-k8s")
        self.sauvage = arc_values("arc-k8s-sauvage")
        self.shared_spec = self.shared["template"]["spec"]
        self.sauvage_spec = self.sauvage["template"]["spec"]

    def test_sauvage_scale_set_serves_the_arc_k8s_label(self) -> None:
        """Mismo `runs-on: arc-k8s`: este scale set lleva la etiqueta explicita
        y arc-k8s no declara ninguna (su etiqueta es su nombre)."""
        self.assertEqual(self.sauvage["runnerScaleSetName"], "arc-k8s-sauvage")
        self.assertEqual(self.sauvage["scaleSetLabels"], ["arc-k8s"])
        self.assertEqual(self.shared["runnerScaleSetName"], "arc-k8s")
        self.assertNotIn("scaleSetLabels", self.shared)

    def test_same_chart_org_secret_and_controller(self) -> None:
        shared_app = arc_application("arc-k8s")
        sauvage_app = arc_application("arc-k8s-sauvage")
        for key in ("githubConfigUrl", "githubConfigSecret", "controllerServiceAccount"):
            self.assertEqual(self.sauvage[key], self.shared[key], key)
        for key in ("repoURL", "chart", "targetRevision"):
            self.assertEqual(
                sauvage_app["spec"]["source"][key], shared_app["spec"]["source"][key], key
            )
        self.assertEqual(sauvage_app["spec"]["project"], shared_app["spec"]["project"])
        self.assertEqual(sauvage_app["spec"]["destination"], shared_app["spec"]["destination"])
        self.assertEqual(sauvage_app["spec"]["syncPolicy"], shared_app["spec"]["syncPolicy"])

    def test_cap_is_three_and_total_stays_thirty_two(self) -> None:
        atlantic = arc_values("arc-k8s-atlantic")
        self.assertEqual(self.sauvage["maxRunners"], 3)
        self.assertEqual(self.shared["maxRunners"], 21)
        self.assertEqual(
            self.shared["maxRunners"]
            + atlantic["maxRunners"]
            + self.sauvage["maxRunners"],
            32,
        )

    def test_sauvage_set_has_no_warm_runners(self) -> None:
        """Los 2 runners calientes (INFRA-334) los pone arc-k8s, en x86."""
        self.assertEqual(self.sauvage["minRunners"], 0)
        self.assertEqual(self.shared["minRunners"], 2)

    def test_sauvage_set_is_pinned_to_sauvage_and_tolerates_edge(self) -> None:
        self.assertEqual(
            self.sauvage_spec["nodeSelector"],
            {"kubernetes.io/arch": "amd64", "kubernetes.io/hostname": "sauvage"},
        )
        self.assertEqual(
            self.sauvage_spec["tolerations"],
            [POOL_DEV_TOLERATION, EDGE_TOLERATION],
        )
        # los ks5-cp-* no llevan taint: el required de control-plane se conserva
        required = self.sauvage_spec["affinity"]["nodeAffinity"][
            "requiredDuringSchedulingIgnoredDuringExecution"
        ]
        self.assertEqual(
            required["nodeSelectorTerms"],
            [
                {
                    "matchExpressions": [
                        {
                            "key": "node-role.kubernetes.io/control-plane",
                            "operator": "DoesNotExist",
                        }
                    ]
                }
            ],
        )

    def test_only_the_sauvage_set_tolerates_edge(self) -> None:
        """arc-k8s no puede caer en sauvage por su cuenta: si recupera la
        toleration de role=edge (o una preferencia por sauvage), este test corta."""
        self.assertNotIn(EDGE_TOLERATION, self.shared_spec["tolerations"])
        self.assertNotIn(
            "preferredDuringSchedulingIgnoredDuringExecution",
            self.shared_spec["affinity"]["nodeAffinity"],
        )
        self.assertNotIn(
            EDGE_TOLERATION, arc_values("arc-k8s-atlantic")["template"]["spec"]["tolerations"]
        )

    def test_pod_template_is_the_same_apart_from_placement(self) -> None:
        """DinD, limites, MTU, sidecar y volumenes: un solo template en tres
        sitios; si uno cambia, cambian los otros."""
        for key in ("initContainers", "containers", "volumes"):
            self.assertEqual(self.sauvage_spec[key], self.shared_spec[key], key)

    def test_sauvage_cap_carries_a_dated_comment(self) -> None:
        """Como arc-k8s: el bloque de comentarios justo encima de maxRunners
        lleva fecha, el ticket y la razon del numero."""
        values_text = arc_application("arc-k8s-sauvage")["spec"]["source"]["helm"]["values"]
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
        self.assertIn("INFRA-1397", joined)
        self.assertIn("md3", joined)
        self.assertIn("21 + 8 + 3 = 32", joined)


if __name__ == "__main__":
    unittest.main()
