"""2026-11-15: atlantic tiene un tope de runners de arc-k8s (8; 4 desde el 2026-11-16).

Con el pool lleno (32/32) atlantic (16 CPU, tambien aloja paseo-0) llego a ~23
runners de arc-k8s: 16 CPU al 99 % y el daemon de Paseo sin CPU. El pool de
`runs-on: arc-k8s` se parte en dos scale sets que comparten esa etiqueta
(`scaleSetLabels: [arc-k8s]` -> `spec.runnerScaleSetLabels`, chart 0.14.1):

  - arc-k8s          atlantic excluido (required NotIn por hostname) y sauvage
                     excluido (no tolera role=edge, ver INFRA-1397 2026-11-16):
                     solo x86;
  - arc-k8s-atlantic maxRunners 4 (8 hasta el 2026-11-16), fijado a atlantic.

2026-11-16 (INFRA-1397): diseno final de tres scale sets con la etiqueta
arc-k8s y 31 plazas: atlantic 4 (min 4), arc-k8s en x86 24 (min 2) y
arc-k8s-sauvage 3 (min 0, tests/test_arc_k8s_sauvage.py). Con 8 en atlantic y
8 en sauvage (40 plazas) atlantic quedaba al 96-99 % de CPU y paseo-0 perdia, y
el md3 de sauvage llegaba al 98-100 %. Atlantic es la primera
prioridad: 4 runners calientes y registrados siempre libres (ARC no tiene
prioridad explicita entre scale sets; se aproxima con minRunners). Este test es
la puerta de la parte de atlantic; el render real con helm lo comprueba
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
        """Mismo `runs-on: arc-k8s` y tambien `arc-k8s-fast` (INFRA-1437: es
        un nodo rapido, los jobs pesados si pueden caer aqui)."""
        self.assertEqual(self.atlantic["runnerScaleSetName"], "arc-k8s-atlantic")
        self.assertEqual(self.atlantic["scaleSetLabels"], ["arc-k8s", "arc-k8s-light"])
        self.assertEqual(self.shared["runnerScaleSetName"], "arc-k8s")
        self.assertEqual(self.shared["scaleSetLabels"], ["arc-k8s", "arc-k8s-light"])

    def test_same_org_secret_and_controller(self) -> None:
        for key in ("githubConfigUrl", "githubConfigSecret", "controllerServiceAccount"):
            self.assertEqual(self.atlantic[key], self.shared[key], key)
        self.assertEqual(
            arc_application("arc-k8s-atlantic")["spec"]["destination"],
            arc_application("arc-k8s")["spec"]["destination"],
        )

    def test_total_capacity_is_thirty_one(self) -> None:
        """24 (x86) + 4 (atlantic) + 3 (sauvage) = 31 (INFRA-1397, 2026-11-16)."""
        sauvage = arc_values("arc-k8s-sauvage")
        self.assertEqual(self.shared["maxRunners"], 24)
        self.assertEqual(self.atlantic["maxRunners"], 4)
        self.assertEqual(sauvage["maxRunners"], 3)
        self.assertEqual(
            self.shared["maxRunners"]
            + self.atlantic["maxRunners"]
            + sauvage["maxRunners"],
            31,
        )

    def test_atlantic_is_first_priority_with_warm_runners(self) -> None:
        """Calentamiento repartido (ARC no tiene prioridad explicita): atlantic
        min == max (4, su tope sin ahogar paseo-0, INFRA-1397), x86 6 desde
        INFRA-1424 (la oleada del CI de dgx-infra ya son 13 jobs y atlantic no
        puede crecer), sauvage sin ninguno."""
        sauvage = arc_values("arc-k8s-sauvage")
        self.assertEqual(self.atlantic["minRunners"], 4)
        self.assertEqual(self.atlantic["minRunners"], self.atlantic["maxRunners"])
        self.assertEqual(self.shared["minRunners"], 6)
        self.assertEqual(sauvage["minRunners"], 0)
        self.assertGreater(self.shared["minRunners"], sauvage["minRunners"])
        self.assertGreater(self.atlantic["minRunners"], sauvage["minRunners"])

    def test_atlantic_set_is_pinned_to_atlantic_only(self) -> None:
        self.assertEqual(
            self.atlantic_spec["nodeSelector"],
            {"kubernetes.io/arch": "amd64", "kubernetes.io/hostname": "atlantic"},
        )
        self.assertNotIn(EDGE_TOLERATION, self.atlantic_spec["tolerations"])

    def test_shared_set_excludes_atlantic_and_sauvage(self) -> None:
        """2026-11-16 (INFRA-1397): arc-k8s solo puede caer en x86. atlantic
        sale por el required NotIn; sauvage por no tolerar role=edge y sin
        nodeAffinity preferida (24 arranques en frio saturaron su md3, un HDD)."""
        node_affinity = self.shared_spec["affinity"]["nodeAffinity"]
        required = node_affinity["requiredDuringSchedulingIgnoredDuringExecution"]
        expressions = required["nodeSelectorTerms"][0]["matchExpressions"]
        self.assertIn(
            {"key": "kubernetes.io/hostname", "operator": "NotIn", "values": ["atlantic"]},
            expressions,
        )
        self.assertIn(
            {"key": "node-role.kubernetes.io/control-plane", "operator": "DoesNotExist"},
            expressions,
        )
        self.assertNotIn(
            "preferredDuringSchedulingIgnoredDuringExecution",
            node_affinity,
        )
        self.assertNotIn(EDGE_TOLERATION, self.shared_spec["tolerations"])
        # el nodeSelector de arc-k8s no fija hostname: el pool se elige por etiqueta
        self.assertNotIn("kubernetes.io/hostname", self.shared_spec["nodeSelector"])

    def test_pod_template_is_the_same_apart_from_placement(self) -> None:
        """DinD, limites, MTU, sidecar y volumenes: un solo template en dos
        sitios; si uno cambia, cambia el otro.

        Excepcion unica (SC-6845, 27-11): los REQUESTS de cpu del runner y de
        DinD divergen a mano en atlantic (500m y 250m frente a 100m y 50m), porque
        aqui los 4 runners calientes comparten nodo con company-0 y paseo-0 y
        x86 no tiene margen para subirlos. La test_atlantic_runner_requests_*
        fija los valores de atlantic y test_requests_de_atlantic_divergen_*
        fija que la divergencia es solo esa."""
        for key in ("initContainers", "containers", "volumes"):
            atlantic = [
                {k: v for k, v in c.items() if k != "resources"}
                for c in self.atlantic_spec[key]
            ]
            shared = [
                {k: v for k, v in c.items() if k != "resources"}
                for c in self.shared_spec[key]
            ]
            self.assertEqual(atlantic, shared, key)

    def _atlantic_request(self, container: str, kind: str) -> dict:
        key = "containers" if kind == "containers" else "initContainers"
        for c in self.atlantic_spec[key]:
            if c["name"] == container:
                return c["resources"]["requests"]
        raise AssertionError(f"{container} not in {kind}")

    def test_atlantic_runner_requests_protect_the_node(self) -> None:
        """SC-6845 (SC-6795): los requests de cpu del runner y de DinD son
        reales (500m y 250m), no 100m/50m: 4 runners calientes + company-0 +
        paseo-0 caben con garantia en los 16 cores de atlantic."""
        self.assertEqual(self._atlantic_request("runner", "containers")["cpu"], "500m")
        self.assertEqual(self._atlantic_request("dind", "initContainers")["cpu"], "250m")

    def test_requests_divergen_only_in_atlantic_cpu(self) -> None:
        """La unica divergencia de resources entre atlantic y arc-k8s son los
        dos requests de cpu de arriba: memoria y limites siguen iguales."""
        for name, key in (("runner", "containers"), ("dind", "initContainers")):
            atlantic = self._atlantic_request(name, key)
            pool = next(
                c["resources"]["requests"]
                for c in self.shared_spec[key]
                if c["name"] == name
            )
            for field in pool:
                if field == "cpu":
                    self.assertNotEqual(atlantic[field], pool[field], name)
                else:
                    self.assertEqual(atlantic[field], pool[field], name)
            # los limits siguen identicos
            atl_limits = next(
                c["resources"]["limits"]
                for c in self.atlantic_spec[key]
                if c["name"] == name
            )
            shared_limits = next(
                c["resources"]["limits"]
                for c in self.shared_spec[key]
                if c["name"] == name
            )
            self.assertEqual(atl_limits, shared_limits, name)

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
        self.assertIn("24 + 8 = 32", joined)  # bloque historico del 2026-11-15
        self.assertIn("atlantic 4 + x86 24 + sauvage 3", joined)  # INFRA-1397


if __name__ == "__main__":
    unittest.main()
