from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SynapseSreFoundationApplicationTest(unittest.TestCase):
    def test_application_is_automated_selfheal_and_non_pruning(self) -> None:
        # INFRA-314: el contrato de sync MANUAL caduco con el gate de sombra
        # (replicas 1 desde 5ef0b84, suspend false desde 304e5a5). Decision
        # del tech-lead: automated + selfHeal. Se mantiene la clausula dura de
        # no-prune (nada de esta app se poda del cluster).
        app = (ROOT / "apps/synapse-sre-foundation.yaml").read_text()
        self.assertIn("name: synapse-sre-foundation", app)
        self.assertIn("targetRevision: deploy/prod", app)
        self.assertIn("path: k8s/sre-foundation", app)
        self.assertIn("selfHeal: true", app)
        self.assertNotIn("prune: true", app)

        root = (ROOT / "kustomization.yaml").read_text()
        self.assertEqual(root.count("apps/synapse-sre-foundation.yaml"), 1)


if __name__ == "__main__":
    unittest.main()
