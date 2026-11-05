"""INFRA-334 (p95 del job de review, criterio 6 de INFRA-298): el pool arc-k8s
no puede volver a nacer frio.

Medido 02-11 con la API de jobs por run sobre los pilotos (n=42 jobs
"Review del PR (PR-Agent)"): espera hasta iniciar el job mediana 33,5 s / p95
139 s (minRunners era 0: cada job pagaba pod + registro) y pull de la imagen
del motor dentro del dind efimero mediana 23,5 s / p95 122 s, con dos runs
clavados en el timeout de 240 s del paso del workflow. El motor cumple (p95
98 s): el defecto es cola + pull. Este test es la puerta:

  1. minRunners >= 1 (runners calientes) — con el numero justificado por el
     comentario fechado de infra/arc.yaml (filosofia del test de sizing);
  2. el sidecar warm-pr-agent existe, va despues de dind, es sidecar nativo
     (restartPolicy: Always: no bloquea el arranque del runner), esta acotado
     (timeout) y es best-effort (|| true: sin Harbor el runner arranca igual);
  3. no introduce credenciales en el pod del runner (el proyecto Harbor se
     sirve anonimo; un secretKeyRef aqui seria una superficie nueva);
  4. solo en arc-k8s: arc-openclaw y arc-skills-eval no corren el motor.
"""

from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
PR_AGENT_DIGEST = re.compile(
    r"^harbor\.e-dani\.com/homelab/pr-agent:0\.46\.0-github_action"
    r"@sha256:[0-9a-f]{64}$"
)


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


class ArcWarmPoolTest(unittest.TestCase):
    def setUp(self) -> None:
        self.values = arc_values("arc-k8s")
        self.init_containers = self.values["template"]["spec"]["initContainers"]
        self.names = [c["name"] for c in self.init_containers]

    def test_pool_keeps_warm_runners(self) -> None:
        """Cola medida 33,5 s de mediana con minRunners 0: el pool no vuelve a
        nacer frio del todo."""
        self.assertGreaterEqual(self.values["minRunners"], 1)
        self.assertLessEqual(self.values["minRunners"], self.values["maxRunners"])

    def test_warm_sidecar_is_ordered_after_dind(self) -> None:
        """El pull necesita el daemon: el sidecar va despues de dind (kubelet lo
        arranca tras su sonda de arranque) y antes del runner."""
        self.assertEqual(
            self.names, ["init-dind-externals", "dind", "warm-pr-agent"]
        )

    def test_warm_sidecar_is_nonblocking_bounded_and_best_effort(self) -> None:
        warm = self.init_containers[2]
        self.assertEqual(warm["name"], "warm-pr-agent")
        # Sidecar nativo: el runner no espera al pull (el camino frio no paga
        # el pull por adelantado en la espera del job).
        self.assertEqual(warm["restartPolicy"], "Always")
        script = " ".join(warm["args"])
        self.assertRegex(script, r"timeout \d+ docker pull")
        self.assertIn("|| true", script)

    def test_warm_sidecar_pulls_the_pinned_image_without_credentials(self) -> None:
        warm = self.init_containers[2]
        env = {item["name"]: item.get("value") for item in warm["env"]}
        self.assertTrue(
            PR_AGENT_DIGEST.match(env["PR_AGENT_IMAGE"]),
            "warm-pr-agent must pull the pinned pr-agent reference",
        )
        for item in warm["env"]:
            self.assertNotIn(
                "valueFrom",
                item,
                "no secret references in the runner pod: the pr-agent Harbor "
                "project is served anonymously (INFRA-334, measured 02-11)",
            )
        self.assertEqual(
            [vm["name"] for vm in warm["volumeMounts"]], ["dind-sock"]
        )
        self.assertNotIn(
            "privileged", warm.get("securityContext", {})
        )

    def test_only_the_shared_pool_warms_pr_agent(self) -> None:
        """arc-openclaw y arc-skills-eval no corren el motor pr-agent: no
        arrastran el sidecar."""
        for name in ("arc-openclaw", "arc-skills-eval"):
            names = [
                c["name"]
                for c in arc_values(name)["template"]["spec"].get(
                    "initContainers", []
                )
            ]
            self.assertNotIn("warm-pr-agent", names, name)


if __name__ == "__main__":
    unittest.main()
