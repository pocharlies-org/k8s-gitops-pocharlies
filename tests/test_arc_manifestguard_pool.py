"""INFRA-1407 (P1 de INFRA-1405): el pool `arc-manifestguard` es el del guard de manifiestos.

Lo que fija este test, leído del YAML (sin clúster):

- La identidad del runner es el SA dedicado `arc-manifestguard-cr-reader`, cuyo RBAC de solo
  lectura vive en k8s-infra-pocharlies/platform/arc/rbac-manifestguard.yaml. Con ese valor puesto,
  el chart no crea su SA `*-gha-rs-no-permission`: la identidad revisada es esa y ninguna otra.
- El pool sigue sin DinD (nada privilegiado) y sin ensanchar `arc-k8s`, que es el runner de toda la
  org: dar CRD-read a su SA se lo daría a cualquier job de CI.
- Colocado en el pool CPU (workload=cpu) con el doble candado sobre los control planes y sin
  tolerar role=edge (sauvage).

El render contra el chart lo vigila scripts/verify_arc_runner_render.sh (CI); este test es la
guarda barata del YAML, al estilo de tests/test_arc_runner_ks5_placement.py.
"""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNNER_IMAGE = "ghcr.io/actions/actions-runner:2.337.0@sha256:e5496277be5d09bc968b3d64911b74e219ac4a3f2edce956a3ecf9271bea1ef4"
SA_NAME = "arc-manifestguard-cr-reader"


def _application(name):
    for document in yaml.safe_load_all((ROOT / "infra/arc.yaml").read_text()):
        if (
            isinstance(document, dict)
            and document.get("kind") == "Application"
            and document.get("metadata", {}).get("name") == name
        ):
            return document
    raise AssertionError(f"Application {name} no existe en infra/arc.yaml")


class ArcManifestguardPoolTest(unittest.TestCase):
    def setUp(self) -> None:
        self.application = _application("arc-manifestguard")
        source = self.application["spec"]["source"]
        self.assertEqual(source["chart"], "gha-runner-scale-set")
        self.assertEqual(source["targetRevision"], "0.14.1")
        self.assertEqual(
            self.application["spec"]["destination"]["namespace"], "arc-runners"
        )
        self.values = yaml.safe_load(source["helm"]["values"])

    def test_the_runner_identity_is_the_dedicated_service_account(self) -> None:
        self.assertEqual(self.values["template"]["spec"]["serviceAccountName"], SA_NAME)

    def test_it_is_its_own_scale_set_and_not_the_shared_pool(self) -> None:
        self.assertEqual(self.values["runnerScaleSetName"], "arc-manifestguard")
        self.assertEqual(self.values["minRunners"], 0)
        self.assertEqual(self.values["maxRunners"], 2)
        # Org: el guard se publica en reusable-ci.yml (INFRA-1409) y cualquier repo lo activa.
        self.assertEqual(self.values["githubConfigUrl"], "https://github.com/pocharlies-org")

    def test_the_pool_has_no_dind_and_no_privileged_container(self) -> None:
        self.assertNotIn("containerMode", self.values)
        rendered = yaml.dump(self.values)
        self.assertNotIn("privileged: true", rendered)
        self.assertNotIn("dind", rendered)

    def test_the_runner_image_is_pinned(self) -> None:
        runner = self.values["template"]["spec"]["containers"][0]
        self.assertEqual(runner["name"], "runner")
        self.assertEqual(runner["image"], RUNNER_IMAGE)
        self.assertEqual(runner["imagePullPolicy"], "IfNotPresent")

    def test_it_sits_on_the_cpu_pool_off_the_control_planes(self) -> None:
        spec = self.values["template"]["spec"]
        self.assertEqual(
            spec["nodeSelector"],
            {"kubernetes.io/arch": "amd64", "workload": "cpu"},
        )
        self.assertEqual(
            spec["affinity"]["nodeAffinity"],
            {
                "requiredDuringSchedulingIgnoredDuringExecution": {
                    "nodeSelectorTerms": [
                        {
                            "matchExpressions": [
                                {
                                    "key": "node-role.kubernetes.io/control-plane",
                                    "operator": "DoesNotExist",
                                }
                            ]
                        }
                    ]
                }
            },
        )
        self.assertNotIn("tolerations", spec)


if __name__ == "__main__":
    unittest.main()
