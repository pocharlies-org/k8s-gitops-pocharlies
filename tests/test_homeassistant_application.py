from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class HomeAssistantApplicationTest(unittest.TestCase):
    """INFRA-557: la Application `homeassistant` (manifiestos en
    k8s-homeassistant-pocharlies, k8s/overlays/prod). Forma del patrón
    (apps/blog.yaml): el diff contra lo vivo debe estar vacío antes del
    primer sync — selfHeal sobre recursos nacidos a mano es un reinicio."""

    def setUp(self) -> None:
        self.application = yaml.safe_load(
            (ROOT / "apps/homeassistant.yaml").read_text(encoding="utf-8")
        )

    def test_application_points_at_homeassistant_repo(self) -> None:
        self.assertEqual(self.application["metadata"]["name"], "homeassistant")
        self.assertEqual(self.application["metadata"]["namespace"], "argocd")
        spec = self.application["spec"]
        self.assertEqual(
            spec["source"],
            {
                "repoURL": "https://github.com/pocharlies-org/k8s-homeassistant-pocharlies",
                "targetRevision": "HEAD",
                "path": "k8s/overlays/prod",
            },
        )
        self.assertEqual(spec["destination"]["namespace"], "homeassistant")

    def test_prune_false_selfheal_and_namespace_created_by_option(self) -> None:
        # INFRA-557: prune: false fijo (los recursos vivos nunca se borran por
        # git); el namespace solo con CreateNamespace=true — el kustomize del repo
        # no incluye namespace.yaml para que el finalizer no arrastre el ns.
        policy = self.application["spec"]["syncPolicy"]
        self.assertIs(policy["automated"]["prune"], False)
        self.assertIs(policy["automated"]["selfHeal"], True)
        self.assertIn("CreateNamespace=true", policy["syncOptions"])
        self.assertIn("ServerSideApply=true", policy["syncOptions"])

    def test_tier_label_sync_wave_and_finalizer(self) -> None:
        meta = self.application["metadata"]
        self.assertEqual(meta["labels"]["e-dani.com/tier"], "app")
        self.assertEqual(meta["annotations"]["argocd.argoproj.io/sync-wave"], "20")
        self.assertEqual(
            meta["finalizers"], ["resources-finalizer.argocd.argoproj.io"]
        )

    def test_root_kustomization_includes_application(self) -> None:
        root = yaml.safe_load((ROOT / "kustomization.yaml").read_text(encoding="utf-8"))
        self.assertIn("apps/homeassistant.yaml", root["resources"])


if __name__ == "__main__":
    unittest.main()
