from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SynapseSreFoundationApplicationTest(unittest.TestCase):
    def test_application_is_manual_and_isolated(self) -> None:
        app = (ROOT / "apps/synapse-sre-foundation.yaml").read_text()
        self.assertIn("name: synapse-sre-foundation", app)
        self.assertIn("targetRevision: deploy/prod", app)
        self.assertIn("path: k8s/sre-foundation", app)
        self.assertNotIn("automated:", app)
        self.assertNotIn("prune: true", app)
        self.assertNotIn("selfHeal: true", app)

        root = (ROOT / "kustomization.yaml").read_text()
        self.assertEqual(root.count("apps/synapse-sre-foundation.yaml"), 1)


if __name__ == "__main__":
    unittest.main()
