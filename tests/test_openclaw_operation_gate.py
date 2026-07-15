from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OpenClawOperationGateTest(unittest.TestCase):
    def runtime_deployment_gate(self) -> tuple[str, str]:
        manifest = (
            ROOT / "argocd/openclaw-operation-admission-gate.yaml"
        ).read_text()
        marker = (
            "kind: ValidatingAdmissionPolicy\n"
            "metadata:\n"
            "  name: openclaw-runtime-deployment-write-gate\n"
        )
        binding_marker = (
            "\n---\n"
            "apiVersion: admissionregistration.k8s.io/v1\n"
            "kind: ValidatingAdmissionPolicyBinding\n"
            "metadata:\n"
            "  name: openclaw-runtime-deployment-write-gate\n"
        )

        self.assertEqual(manifest.count(marker), 1)
        _, runtime_documents = manifest.split(marker, 1)
        policy, binding = runtime_documents.split(binding_marker, 1)
        return policy, binding

    def test_gate_is_fail_closed_and_scoped_to_argocd_applications(self) -> None:
        manifest = (
            ROOT / "argocd/openclaw-operation-admission-gate.yaml"
        ).read_text()

        self.assertIn("failurePolicy: Fail", manifest)
        self.assertIn("- applications", manifest)
        self.assertIn("- CREATE", manifest)
        self.assertIn("- UPDATE", manifest)
        self.assertIn("- DELETE", manifest)
        self.assertIn("object.metadata.namespace != 'argocd'", manifest)
        self.assertIn("object.metadata.name != 'openclaw-qwen36'", manifest)
        self.assertIn("|| !has(object.operation)", manifest)
        self.assertIn("validationActions:\n    - Deny", manifest)

    def test_operation_requires_one_exact_gitops_approval(self) -> None:
        manifest = (
            ROOT / "argocd/openclaw-operation-admission-gate.yaml"
        ).read_text()

        for annotation in (
            "operations.pocharlies.org/state-writer-lease",
            "operations.pocharlies.org/approved-revision",
            "operations.pocharlies.org/approval-id",
            "operations.pocharlies.org/approval-sequence",
            "operations.pocharlies.org/approved-prune",
        ):
            self.assertIn(annotation, manifest)
        self.assertIn("matches('^[0-9a-f]{40}$')", manifest)
        self.assertIn("object.operation.sync.revision ==", manifest)
        self.assertIn("object.operation.info.size() == 2", manifest)
        self.assertIn("item.name == 'approval-id'", manifest)
        self.assertIn("item.name == 'approval-sequence'", manifest)
        self.assertIn("matches('^[0-9]{14}$')", manifest)
        self.assertIn("has(object.operation.sync.prune)", manifest)
        self.assertIn(
            "object.operation.sync.syncOptions == oldObject.spec.syncPolicy.syncOptions",
            manifest,
        )

    def test_operation_forbids_all_argocd_sync_bypass_fields(self) -> None:
        manifest = (
            ROOT / "argocd/openclaw-operation-admission-gate.yaml"
        ).read_text()

        for field in (
            "autoHealAttemptsCount",
            "dryRun",
            "manifests",
            "resources",
            "revisions",
            "source",
            "sources",
            "syncStrategy",
        ):
            self.assertIn(
                f"!has(object.operation.sync.{field})",
                manifest,
            )
        self.assertIn("!has(object.operation.retry)", manifest)
        self.assertIn("selective sync", manifest)

    def test_spec_status_and_running_operation_are_controller_owned(self) -> None:
        manifest = (
            ROOT / "argocd/openclaw-operation-admission-gate.yaml"
        ).read_text()

        self.assertIn("|| object.spec == oldObject.spec", manifest)
        self.assertIn("object.status == oldObject.status", manifest)
        self.assertIn("object.operation == oldObject.operation", manifest)
        self.assertIn("Running-to-Terminating", manifest)
        self.assertIn("argocd:argocd-server", manifest)

    def test_approval_sequence_is_strictly_monotonic(self) -> None:
        manifest = (
            ROOT / "argocd/openclaw-operation-admission-gate.yaml"
        ).read_text()

        self.assertIn("has(oldObject.operation)", manifest)
        self.assertIn("oldObject.status.operationState.operation.info.exists", manifest)
        self.assertIn("<= int(item.value)", manifest)
        self.assertIn("strictly newer UTC value", manifest)

    def test_only_dedicated_executor_can_create_an_operation(self) -> None:
        manifest = (
            ROOT / "argocd/openclaw-operation-admission-gate.yaml"
        ).read_text()

        self.assertIn("kind: ServiceAccount", manifest)
        self.assertIn("name: openclaw-operation-executor", manifest)
        self.assertIn("automountServiceAccountToken: false", manifest)
        self.assertIn(
            "system:serviceaccount:argocd:openclaw-operation-executor",
            manifest,
        )
        self.assertIn('verbs: ["get", "patch"]', manifest)
        self.assertIn('resourceNames: ["openclaw-qwen36"]', manifest)

    def test_metadata_and_delete_paths_are_controller_owned(self) -> None:
        manifest = (
            ROOT / "argocd/openclaw-operation-admission-gate.yaml"
        ).read_text()

        for field in (
            "annotations",
            "labels",
            "finalizers",
            "ownerReferences",
        ):
            self.assertIn(
                f"object.metadata.{field} == oldObject.metadata.{field}",
                manifest,
            )
        self.assertIn("name: openclaw-application-delete-gate", manifest)
        self.assertIn("name: openclaw-application-create-gate", manifest)
        self.assertIn("Only the root GitOps application controller may delete", manifest)
        self.assertIn("Only the root GitOps application controller may create", manifest)

    def test_runbook_uses_clean_short_lived_executor_identity(self) -> None:
        runbook = (
            ROOT / "docs/runbook-openclaw-controlled-operation.md"
        ).read_text()

        self.assertIn("EXEC_KUBECONFIG", runbook)
        self.assertIn("create token", runbook)
        self.assertIn("auth whoami", runbook)
        self.assertIn("system:serviceaccount:argocd:openclaw-operation-executor", runbook)
        self.assertIn("--dry-run=server -p \"$PATCH\"", runbook)
        self.assertNotIn('kubectl --token="$TOKEN"', runbook)

    def test_only_gitops_controller_can_change_protected_approvals(self) -> None:
        manifest = (
            ROOT / "argocd/openclaw-operation-admission-gate.yaml"
        ).read_text()

        self.assertIn(
            "system:serviceaccount:argocd:argocd-application-controller",
            manifest,
        )
        self.assertIn("oldObject.metadata.annotations", manifest)
        self.assertIn("inactive without stale approvals", manifest)

        root = (ROOT / "kustomization.yaml").read_text()
        self.assertEqual(
            root.count("argocd/openclaw-operation-admission-gate.yaml"),
            1,
        )

    def test_runtime_deployment_gate_covers_direct_writes_and_scale(self) -> None:
        policy, binding = self.runtime_deployment_gate()

        self.assertIn("failurePolicy: Fail", policy)
        for operation in ("CREATE", "UPDATE", "DELETE"):
            self.assertIn(f"          - {operation}", policy)
        self.assertIn("          - deployments\n", policy)
        self.assertIn("          - deployments/scale\n", policy)
        self.assertNotIn("deployments/status", policy)
        self.assertNotIn("          - '*'", policy)
        self.assertIn("validationActions:\n    - Deny", binding)
        self.assertIn("    - Audit", binding)

    def test_runtime_deployment_gate_has_exact_namespace_scope(self) -> None:
        policy, binding = self.runtime_deployment_gate()

        self.assertIn(
            "expression: request.namespace == 'openclaw-qwen36'",
            policy,
        )
        self.assertIn("namespaceSelector:", binding)
        self.assertIn("kubernetes.io/metadata.name: openclaw-qwen36", binding)
        self.assertNotIn("openclaw-synapse", policy + binding)
        self.assertNotIn("objectSelector:", policy + binding)

    def test_runtime_deployment_gate_has_no_name_or_label_bypass(self) -> None:
        policy, _ = self.runtime_deployment_gate()

        self.assertNotRegex(policy, r"\brequest\.name\b")
        self.assertNotIn("object.metadata.labels", policy)
        self.assertNotIn("oldObject.metadata.labels", policy)

    def test_runtime_deployment_gate_allows_only_the_argo_controller(self) -> None:
        policy, _ = self.runtime_deployment_gate()
        argo_controller = (
            "system:serviceaccount:argocd:argocd-application-controller"
        )

        self.assertEqual(policy.count(argo_controller), 1)
        self.assertIn("request.userInfo.username ==", policy)
        self.assertIn("including rollout\n        restart and scale", policy)
        self.assertNotIn("request.userInfo.groups", policy)

    def test_adversarial_harness_is_server_dry_run_only(self) -> None:
        script_path = ROOT / "scripts/verify_openclaw_deployment_write_gate.sh"
        script = script_path.read_text()

        subprocess.run(["bash", "-n", script_path], check=True)
        for command in (
            "create deployment",
            "patch deployment",
            "rollout restart",
            "scale \"deployment/$DEPLOYMENT\"",
            "delete \"deployment/$DEPLOYMENT\"",
            "--subresource=status",
            "kubectl --as=\"$ARGO_USER\"",
            "Synapse namespace UPDATE",
            "unrelated namespace CREATE",
        ):
            self.assertIn(command, script)
        self.assertGreaterEqual(script.count("--dry-run=server"), 9)
        self.assertNotIn("--dry-run=none", script)
        self.assertNotIn("kubectl apply", script)


if __name__ == "__main__":
    unittest.main()
