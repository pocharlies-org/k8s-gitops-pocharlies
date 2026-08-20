from pathlib import Path
import subprocess
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

    def test_synapse_uses_fixed_scope_ephemeral_manual_sync_executor(self) -> None:
        executor_path = ROOT / "scripts/execute_openclaw_synapse_manual_sync.sh"
        executor = executor_path.read_text(encoding="utf-8")

        subprocess.run(["bash", "-n", executor_path], check=True)
        self.assertIn('readonly APP_NAMESPACE="argocd"', executor)
        self.assertIn('readonly APP_NAME="openclaw-synapse"', executor)
        self.assertIn('MODE="dry-run-only"', executor)
        self.assertIn("create token", executor)
        self.assertIn("--duration=10m", executor)
        self.assertIn('--rawfile token "$EXEC_TOKEN"', executor)
        self.assertNotIn('--token="$TOKEN"', executor)
        self.assertNotIn("set-credentials", executor)
        self.assertIn("auth whoami", executor)
        self.assertIn("openclaw-operation-executor", executor)
        self.assertIn('--dry-run=server -p "$PATCH"', executor)
        self.assertIn('status: {operationState: null}', executor)
        self.assertIn('initiatedBy: {}', executor)
        self.assertIn('info: [{name: "reason", value: $reason}]', executor)
        self.assertIn('retry: {}', executor)
        self.assertIn('"CreateNamespace=true", "ServerSideApply=true"', executor)
        self.assertNotIn('kubectl --token="$TOKEN"', executor)
        self.assertNotIn("openclaw-qwen36\"", executor)
        self.assertNotIn("prune:", executor)
        self.assertNotIn("--force", executor)

        persisted = executor.split("# This is the only persisted request", 1)[1]
        self.assertEqual(persisted.count("patch application"), 1)
        self.assertIn('--kubeconfig="$EXEC_KUBECONFIG"', persisted)
        self.assertNotIn("--dry-run=server", persisted)

    def test_synapse_manual_sync_executor_is_documented_as_sanctioned(self) -> None:
        runbook = (
            ROOT / "docs/runbook-openclaw-controlled-operation.md"
        ).read_text(encoding="utf-8")

        self.assertIn("scripts/execute_openclaw_synapse_manual_sync.sh", runbook)
        self.assertIn("does not extend the qwen36 approval gate", runbook)
        self.assertIn("separate admission policy confines", runbook)

    def test_synapse_executor_admission_gate_is_exact_scope(self) -> None:
        manifest = (
            ROOT / "argocd/openclaw-operation-admission-gate.yaml"
        ).read_text(encoding="utf-8")
        policy = manifest.split(
            "name: openclaw-synapse-manual-sync-executor-gate", 1
        )[1].split("kind: ValidatingAdmissionPolicyBinding", 1)[0]

        self.assertIn("object.spec == oldObject.spec", policy)
        self.assertIn("object.metadata.annotations == oldObject.metadata.annotations", policy)
        self.assertIn("object.metadata.generateName == oldObject.metadata.generateName", policy)
        self.assertIn("oldObject.status.operationState.phase in", policy)
        self.assertIn("!has(object.status.operationState)", policy)
        self.assertIn("!has(oldObject.operation)", policy)
        self.assertIn("has(object.operation)", policy)
        self.assertIn("object.operation.info.size() == 1", policy)
        self.assertIn("!has(object.operation.initiatedBy.automated)", policy)
        self.assertIn("object.operation.sync.revision.matches('^[0-9a-f]{40}$')", policy)
        self.assertIn("object.operation.sync.syncOptions ==", policy)
        self.assertIn("!has(object.operation.sync.prune)", policy)
        self.assertIn("!has(object.operation.sync.resources)", policy)
        self.assertIn("!has(object.operation.sync.source)", policy)
        self.assertIn("!has(object.operation.retry.limit)", policy)
        self.assertIn("!has(object.operation.retry.refresh)", policy)


if __name__ == "__main__":
    unittest.main()
