from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OpenClawOperationGateTest(unittest.TestCase):
    def test_gate_is_fail_closed_and_scoped_to_argocd_applications(self) -> None:
        manifest = (
            ROOT / "argocd/openclaw-operation-admission-gate.yaml"
        ).read_text()

        self.assertIn("failurePolicy: Fail", manifest)
        self.assertIn("- applications", manifest)
        self.assertIn("- UPDATE", manifest)
        self.assertIn("object.metadata.namespace != 'argocd'", manifest)
        self.assertIn("object.metadata.name != 'openclaw-qwen36'", manifest)
        self.assertIn("|| !has(object.operation)", manifest)
        self.assertIn("validationActions:\n    - Deny", manifest)

    def test_only_gitops_controller_can_activate_writer_gate(self) -> None:
        manifest = (
            ROOT / "argocd/openclaw-operation-admission-gate.yaml"
        ).read_text()

        self.assertIn(
            "operations.pocharlies.org/state-writer-lease",
            manifest,
        )
        self.assertIn(
            "system:serviceaccount:argocd:argocd-application-controller",
            manifest,
        )

        root = (ROOT / "kustomization.yaml").read_text()
        self.assertEqual(
            root.count("argocd/openclaw-operation-admission-gate.yaml"),
            1,
        )

    def test_openclaw_application_activates_the_tested_writer_lease(self) -> None:
        application = (ROOT / "apps/openclaw-qwen36.yaml").read_text()

        self.assertIn(
            "operations.pocharlies.org/state-writer-lease: active",
            application,
        )
        self.assertIn("targetRevision: deploy/prod", application)


if __name__ == "__main__":
    unittest.main()
