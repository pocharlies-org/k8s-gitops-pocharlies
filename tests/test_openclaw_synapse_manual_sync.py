from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OpenClawSynapseManualSyncTest(unittest.TestCase):
    def test_synapse_requires_an_explicit_sync(self) -> None:
        application = (ROOT / "apps/openclaw-synapse.yaml").read_text(
            encoding="utf-8"
        )

        self.assertIn("name: openclaw-synapse", application)
        self.assertIn("targetRevision: deploy/prod", application)
        self.assertIn("syncPolicy:", application)
        self.assertIn("syncOptions:", application)
        self.assertNotIn("automated:", application)
        self.assertNotIn("selfHeal: true", application)


if __name__ == "__main__":
    unittest.main()
