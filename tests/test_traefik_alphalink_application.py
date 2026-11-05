from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class TraefikAlphalinkApplicationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.application = yaml.safe_load(
            (ROOT / "infra/traefik-alphalink.yaml").read_text(encoding="utf-8")
        )

    def test_application_pins_chart_and_gitops_values(self) -> None:
        self.assertEqual(self.application["metadata"]["name"], "traefik-alphalink")
        sources = self.application["spec"]["sources"]
        self.assertEqual(
            sources[0],
            {
                "repoURL": "https://traefik.github.io/charts",
                "chart": "traefik",
                "targetRevision": "40.2.0",
                "helm": {
                    "releaseName": "traefik-alphalink",
                    "valueFiles": ["$values/networking/traefik-alphalink/values.yaml"],
                },
            },
        )
        self.assertEqual(
            sources[1]["repoURL"],
            "https://github.com/pocharlies-org/k8s-infra-pocharlies",
        )
        self.assertEqual(sources[1]["targetRevision"], "main")
        self.assertEqual(sources[1]["ref"], "values")
        self.assertNotIn("automated", self.application["spec"]["syncPolicy"])
        self.assertEqual(
            self.application["spec"]["destination"]["namespace"], "traefik-alphalink"
        )

    def test_root_kustomization_includes_application(self) -> None:
        root = yaml.safe_load((ROOT / "kustomization.yaml").read_text(encoding="utf-8"))
        self.assertIn("infra/traefik-alphalink.yaml", root["resources"])


if __name__ == "__main__":
    unittest.main()
