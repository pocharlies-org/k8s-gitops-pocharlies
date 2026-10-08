from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class FrigateApplicationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.application = yaml.safe_load(
            (ROOT / "apps/frigate.yaml").read_text(encoding="utf-8")
        )

    def test_application_points_at_frigate_repo(self) -> None:
        # INFRA-710 R4: igual que argocd/application.yaml de k8s-frigate-pocharlies.
        self.assertEqual(self.application["metadata"]["name"], "frigate")
        self.assertEqual(self.application["metadata"]["namespace"], "argocd")
        spec = self.application["spec"]
        self.assertEqual(
            spec["source"],
            {
                "repoURL": "https://github.com/pocharlies-org/k8s-frigate-pocharlies",
                "targetRevision": "main",
                "path": "k8s",
            },
        )
        self.assertEqual(spec["destination"]["namespace"], "frigate")

    def test_prune_true_and_namespace_created_by_the_application(self) -> None:
        # Excepción a `prune: false` de las apps normales (ARCHITECTURE.md §5): las NetworkPolicy
        # suman y una regla quitada de git debe desaparecer. Los PVC llevan Prune=false,Delete=false
        # y el namespace lo crea CreateNamespace=true (no hay objeto Namespace en el repo de Frigate).
        policy = self.application["spec"]["syncPolicy"]
        self.assertIs(policy["automated"]["prune"], True)
        self.assertIs(policy["automated"]["selfHeal"], True)
        self.assertIn("CreateNamespace=true", policy["syncOptions"])
        self.assertIn("ServerSideApply=true", policy["syncOptions"])

    def test_root_kustomization_includes_application(self) -> None:
        root = yaml.safe_load((ROOT / "kustomization.yaml").read_text(encoding="utf-8"))
        self.assertIn("apps/frigate.yaml", root["resources"])


if __name__ == "__main__":
    unittest.main()
