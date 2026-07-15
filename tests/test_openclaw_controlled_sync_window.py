from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OpenClawControlledSyncWindowTest(unittest.TestCase):
    def test_automated_window_stays_closed_but_manual_recovery_is_allowed(self) -> None:
        project = (ROOT / "argocd/project-openclaw-controlled.yaml").read_text()

        self.assertIn('schedule: "0 5 * * *"', project)
        self.assertIn('duration: 22h', project)
        self.assertIn('manualSync: true', project)
        self.assertNotIn('manualSync: false', project)
        self.assertIn('after the state-writer lease rollout gate', project)

    def test_application_activates_the_admission_gate_from_gitops(self) -> None:
        application = (ROOT / "apps/openclaw-qwen36.yaml").read_text()

        self.assertIn(
            "operations.pocharlies.org/state-writer-lease: active",
            application,
        )


if __name__ == "__main__":
    unittest.main()
