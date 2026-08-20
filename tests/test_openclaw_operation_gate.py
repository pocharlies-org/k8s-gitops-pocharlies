import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
PATCH_FILTER = ROOT / "scripts/openclaw_operation_atomic_patch.jq"


def operation_application(
    *,
    phase: str | None = "Succeeded",
    prune: str = "false",
    operation_present: bool = False,
) -> dict:
    application = {
        "metadata": {
            "resourceVersion": "99986753",
            "annotations": {
                "operations.pocharlies.org/state-writer-lease": "active",
                "operations.pocharlies.org/approved-revision": "a" * 40,
                "operations.pocharlies.org/approval-id": "openclaw-prod-sync-a1b2c3d4",
                "operations.pocharlies.org/approval-sequence": "20260715090000",
                "operations.pocharlies.org/approved-prune": prune,
            },
        },
        "spec": {
            "syncPolicy": {
                "syncOptions": [
                    "CreateNamespace=true",
                    "ServerSideApply=true",
                ]
            }
        },
        "status": {
            "health": {"status": "Healthy"},
            "sync": {"status": "OutOfSync"},
        },
    }
    if phase is not None:
        application["status"]["operationState"] = {
            "phase": phase,
            "operation": {
                "info": [
                    {"name": "approval-sequence", "value": "20260715070027"}
                ]
            },
        }
    if operation_present:
        application["operation"] = {"sync": {"revision": "b" * 40}}
    return application


def build_operation_patch(application: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["jq", "-ce", "-f", str(PATCH_FILTER)],
        input=json.dumps(application),
        text=True,
        capture_output=True,
        check=False,
    )


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

    def test_argocd_server_termination_preserves_every_other_status_field(self) -> None:
        manifest = (
            ROOT / "argocd/openclaw-operation-admission-gate.yaml"
        ).read_text()

        status_fields = (
            "conditions",
            "controllerNamespace",
            "health",
            "history",
            "observedAt",
            "reconciledAt",
            "resourceHealthSource",
            "resources",
            "sourceHydrator",
            "sourceType",
            "sourceTypes",
            "summary",
            "sync",
        )
        operation_state_fields = (
            "finishedAt",
            "message",
            "operation",
            "retryCount",
            "startedAt",
            "syncResult",
        )

        for field in status_fields:
            with self.subTest(status_field=field):
                self.assertGreaterEqual(
                    manifest.count(
                        f"has(object.status.{field}) == "
                        f"has(oldObject.status.{field})"
                    ),
                    2,
                )
                self.assertGreaterEqual(
                    manifest.count(
                        f"object.status.{field} == oldObject.status.{field}"
                    ),
                    2,
                )

        for field in operation_state_fields:
            with self.subTest(operation_state_field=field):
                self.assertIn(
                    f"has(object.status.operationState.{field}) == "
                    f"has(oldObject.status.operationState.{field})",
                    manifest,
                )
                self.assertIn(
                    f"object.status.operationState.{field} == "
                    f"oldObject.status.operationState.{field}",
                    manifest,
                )

    def test_executor_status_exception_is_terminal_atomic_and_exact(self) -> None:
        manifest = (
            ROOT / "argocd/openclaw-operation-admission-gate.yaml"
        ).read_text()

        self.assertGreaterEqual(
            manifest.count(
                "oldObject.status.operationState.phase in "
                "['Succeeded', 'Failed', 'Error']"
            ),
            2,
        )
        self.assertIn("&& !has(oldObject.operation)", manifest)
        self.assertIn("&& has(object.operation)", manifest)
        self.assertIn("&& !has(object.status.operationState)", manifest)
        self.assertIn(
            "Running and Terminating state must never be\n"
            "        cleared or replaced by the executor",
            manifest,
        )

        status_fields = (
            "conditions",
            "controllerNamespace",
            "health",
            "history",
            "observedAt",
            "reconciledAt",
            "resourceHealthSource",
            "resources",
            "sourceHydrator",
            "sourceType",
            "sourceTypes",
            "summary",
            "sync",
        )
        for field in status_fields:
            with self.subTest(status_field=field):
                self.assertIn(
                    f"has(object.status.{field}) == "
                    f"has(oldObject.status.{field})",
                    manifest,
                )
                self.assertIn(
                    f"object.status.{field} == oldObject.status.{field}",
                    manifest,
                )

    def test_atomic_patch_builder_replaces_terminal_state_and_keeps_prune_explicit(self) -> None:
        for phase in ("Succeeded", "Failed", "Error", None):
            for prune, expected_prune in (("false", False), ("true", True)):
                with self.subTest(phase=phase, prune=prune):
                    result = build_operation_patch(
                        operation_application(phase=phase, prune=prune)
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    patch = json.loads(result.stdout)
                    self.assertEqual(
                        set(patch), {"metadata", "operation", "status"}
                    )
                    self.assertEqual(
                        patch["metadata"], {"resourceVersion": "99986753"}
                    )
                    self.assertEqual(patch["status"], {"operationState": None})
                    self.assertIs(
                        patch["operation"]["sync"]["prune"], expected_prune
                    )
                    self.assertEqual(
                        patch["operation"]["sync"]["revision"], "a" * 40
                    )
                    self.assertEqual(
                        patch["operation"]["sync"]["syncOptions"],
                        ["CreateNamespace=true", "ServerSideApply=true"],
                    )
                    self.assertNotIn("resources", patch["operation"]["sync"])
                    self.assertNotIn("source", patch["operation"]["sync"])
                    self.assertNotIn("retry", patch["operation"])

    def test_atomic_patch_builder_rejects_nonterminal_or_inflight_state(self) -> None:
        for phase in ("Running", "Terminating", "Unknown", ""):
            with self.subTest(phase=phase):
                result = build_operation_patch(operation_application(phase=phase))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("previous operationState is not terminal", result.stderr)

        result = build_operation_patch(
            operation_application(operation_present=True)
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("an operation is already present", result.stderr)

        missing_phase = operation_application()
        del missing_phase["status"]["operationState"]["phase"]
        result = build_operation_patch(missing_phase)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("previous operationState is not terminal", result.stderr)

    def test_atomic_patch_builder_rejects_incomplete_or_stale_input(self) -> None:
        cases = []

        inactive = operation_application()
        inactive["metadata"]["annotations"][
            "operations.pocharlies.org/state-writer-lease"
        ] = "inactive"
        cases.append((inactive, "writer lease is not active"))

        missing_resource_version = operation_application()
        del missing_resource_version["metadata"]["resourceVersion"]
        cases.append(
            (missing_resource_version, "resourceVersion is missing or invalid")
        )

        missing_options = operation_application()
        del missing_options["spec"]["syncPolicy"]["syncOptions"]
        cases.append((missing_options, "GitOps syncOptions are missing or invalid"))

        bad_prune = operation_application(prune="False")
        cases.append((bad_prune, "approved prune decision is invalid"))

        for application, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                result = build_operation_patch(application)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr)

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
        self.assertIn(
            'resourceNames: ["openclaw-qwen36", "openclaw-synapse"]',
            manifest,
        )
        self.assertEqual(manifest.count("resourceNames:"), 1)

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
        executor = (
            ROOT / "scripts/execute_openclaw_controlled_operation.sh"
        ).read_text()

        self.assertIn("scripts/execute_openclaw_controlled_operation.sh", runbook)
        self.assertIn("EXEC_KUBECONFIG", executor)
        self.assertIn("create token", executor)
        self.assertIn("auth whoami", executor)
        self.assertIn("openclaw-operation-executor", executor)
        self.assertIn("--dry-run=server -p \"$PATCH\"", executor)
        self.assertNotIn('kubectl --token="$TOKEN"', executor)

    def test_executor_uses_one_atomic_persisted_merge_patch(self) -> None:
        executor_path = ROOT / "scripts/execute_openclaw_controlled_operation.sh"
        executor = executor_path.read_text()
        patch_filter = PATCH_FILTER.read_text()

        subprocess.run(["bash", "-n", executor_path], check=True)
        self.assertIn('MODE="dry-run-only"', executor)
        self.assertIn("# This is the only persisted request", executor)
        self.assertEqual(executor.count("--dry-run=server"), 1)
        persisted_section = executor.split(
            "# This is the only persisted request", 1
        )[1]
        self.assertEqual(persisted_section.count("patch application"), 1)
        self.assertNotIn("--dry-run=server", persisted_section)
        self.assertIn("resourceVersion: .metadata.resourceVersion", patch_filter)
        self.assertIn("operationState: null", patch_filter)
        self.assertIn(
            "previous operationState is not terminal",
            patch_filter,
        )

    def test_operation_gate_adversarial_harness_is_server_dry_run_only(self) -> None:
        script_path = ROOT / "scripts/verify_openclaw_operation_atomic_gate.sh"
        script = script_path.read_text()

        subprocess.run(["bash", "-n", script_path], check=True)
        for scenario in (
            "dedicated executor atomic consume",
            "dedicated executor stale resourceVersion CAS",
            "operation-only stale-state retention",
            "terminal-state clear without approval consumption",
            "operationState replacement instead of deletion",
            "atomic consume with sibling status tamper",
            "Argo controller cannot impersonate operation executor",
            "argocd-server exact Running-to-Terminating transition",
            "argocd-server termination with health tamper",
            "argocd-server termination with sync tamper",
            "argocd-server termination with history tamper",
            "argocd-server termination with resources tamper",
            "argocd-server termination with message tamper",
            "argocd-server termination with syncResult tamper",
            "argocd-server termination with startedAt tamper",
            "argocd-server termination with finishedAt tamper",
            "argocd-server termination with retryCount tamper",
        ):
            self.assertIn(scenario, script)
        self.assertGreaterEqual(script.count("--dry-run=server"), 17)
        self.assertIn("--termination-only", script)
        self.assertIn("expect_conflict", script)
        self.assertNotIn("--execute", script)
        self.assertNotIn("kubectl apply", script)

    def test_runbook_records_argocd_28701_and_live_prune_mismatch(self) -> None:
        runbook = (
            ROOT / "docs/runbook-openclaw-controlled-operation.md"
        ).read_text()

        self.assertIn("https://github.com/argoproj/argo-cd/issues/28701", runbook)
        self.assertIn("Argo CD v3.4.2", runbook)
        self.assertIn("a28d18d5a3764fcdff06bf9582bfcbd443cab577", runbook)
        self.assertIn("explicitly used `prune: false`", runbook)
        self.assertIn("operation.sync.prune: true", runbook)

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
            "kubectl rollout restart equivalent",
            "kubectl.kubernetes.io/restartedAt",
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
