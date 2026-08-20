# OpenClaw controlled Argo operation

The `openclaw-qwen36` Application is closed by default. A manual sync is valid
only when a reviewed GitOps change supplies one complete approval bundle:

```yaml
operations.pocharlies.org/state-writer-lease: active
operations.pocharlies.org/approved-revision: <full 40-character commit SHA>
operations.pocharlies.org/approval-id: <unique lowercase change id>
operations.pocharlies.org/approval-sequence: <UTC YYYYMMDDhhmmss>
operations.pocharlies.org/approved-prune: "false"
```

The operation must set the same full commit SHA, include exactly two
`operation.info` entries named `approval-id` and `approval-sequence`, set the
reviewed prune decision explicitly, and copy `spec.syncPolicy.syncOptions`
exactly. It must be a complete sync of the existing Application spec. Selective
resources, local manifests, source overrides, multi-source revisions, custom
sync strategies, retry/refresh policies, and differing sync options are denied.
`initiatedBy` is treated as informational and never as authorization.

## Argo CD 3.4 operationState mitigation

Argo CD [issue #28701](https://github.com/argoproj/argo-cd/issues/28701)
documents that `ApplicationController.setOperationState` uses JSON merge patch
while fields such as `SyncOperation.prune` and `resources` use `omitempty`.
Fields absent from the newly marshalled operation can therefore survive from a
previous terminal `status.operationState`. The upstream workaround is to clear
that state in the same merge patch that creates the next `.operation`.

This affected production on 2026-07-15 with Argo CD v3.4.2. The submitted
OpenClaw operation at revision
`a28d18d5a3764fcdff06bf9582bfcbd443cab577` explicitly used `prune: false`, but
its terminal state (`Succeeded`, 07:02:42Z to 07:18:53Z) retained
`status.operationState.operation.sync.prune: true`. Treat the terminal
`operationState` as an unsafe source for the next operation even when that
operation succeeded.

Do not use the Argo UI or `argocd app sync` for this protected Application:
Argo 3.4 adds source, strategy, and retry fields that the policy deliberately
rejects. Use only the repository executor. It creates a ten-minute TokenRequest
for the dedicated ServiceAccount and a clean temporary kubeconfig, never a
long-lived ServiceAccount secret. Supplying `--token` to the normal admin
kubeconfig is unsafe because its client certificate can still authenticate the
request as `system:admin`.

```sh
# Optional admission/RBAC preview. This never changes the Application.
scripts/execute_openclaw_controlled_operation.sh --dry-run-only

# With an OPEN approval and the previous terminal operationState, exercise the
# atomic consume denials plus the stale-resourceVersion CAS. Dry-run only.
scripts/verify_openclaw_operation_atomic_gate.sh --consume-only

# After reviewing the preview, submit exactly one persisted merge PATCH.
# --execute repeats the server dry-run against the same resourceVersion first.
scripts/execute_openclaw_controlled_operation.sh --execute

# While a real operation is Running, exercise the exact Argo-server termination
# exception and prove status/operationState sibling tampering is denied.
scripts/verify_openclaw_operation_atomic_gate.sh --termination-only
```

The persisted request has exactly this top-level shape:

```json
{
  "metadata": {"resourceVersion": "<read resourceVersion>"},
  "operation": {"sync": {"revision": "<approved SHA>", "prune": false,
    "syncOptions": ["<exact GitOps options>"]}, "info": [
      {"name": "approval-id", "value": "<approved id>"},
      {"name": "approval-sequence", "value": "<approved UTC sequence>"}
    ]},
  "status": {"operationState": null}
}
```

The executor rejects an existing `.operation`, a previous `Running` or
`Terminating` operationState, malformed/inactive approval, or missing GitOps
sync options before sending a patch. `metadata.resourceVersion` makes a race
with controller reconciliation fail with `Conflict`. The server dry-run must
succeed only during the reviewed window; `--execute` then sends the
byte-identical merge patch once. Never clear `operationState` in a separate
request. A second update is denied while the operation is in flight.

Only the Argo application controller may change the Application spec, metadata,
status, an in-flight operation, or delete the Application. The Argo server has
one narrow exception: it may change a running operation's `phase` to
`Terminating`. Presence and value of every other `ApplicationStatus` field and
every other `OperationState` field must remain exact. This prevents two-request
spec overrides, deletion-approval/finalizer bypasses, forged health/history,
and corruption of the status-backed consumption ledger.

The executor has one additional status exception during approval consumption:
it may remove a previous `Succeeded`, `Failed`, or `Error` operationState in the
same request that creates `.operation`. Admission denies this for `Running` or
`Terminating` and requires every other field in the v3.4.2
`ApplicationStatus` schema to retain both its presence and exact value. When an
Argo CD upgrade changes that status schema, update the explicit comparison and
rerun the server-side policy type check before upgrading the CRD.

## Independent `openclaw-synapse` manual sync

`openclaw-synapse` is intentionally manual but does not use the qwen36 approval
bundle. Its sanctioned path is
`scripts/execute_openclaw_synapse_manual_sync.sh --revision <40-hex> --reason
<nonempty> --dry-run-only` as a standalone preflight, followed by the same
arguments with `--execute`. The execute invocation performs its own server-side
dry run and persists those exact patch bytes under a resourceVersion CAS. The
executor is fixed to the `argocd/openclaw-synapse` Application,
uses the same ten-minute `openclaw-operation-executor` ServiceAccount identity,
and submits no prune or force option. Granting that identity `get` and `patch`
on this second named Application does not extend the qwen36 approval gate: all
of that gate's validations still short-circuit unless the Application name is
`openclaw-qwen36`. A separate admission policy confines the shared executor
identity to the exact Synapse operation and terminal-status cleanup shape.

Direct creation and deletion are denied, including recreation after restore and
namespace teardown, until the root GitOps controller performs the change. If
that controller is unavailable, treat policy suspension as a break-glass
incident requiring its own reviewed GitOps change and an explicit rollback; do
not recreate the Application, delete finalizers, or add
`argocd.argoproj.io/deletion-approved` manually.

The UTC approval sequence is strictly monotonic. After Argo records it in the
previous operation state, admission rejects the same or any older sequence,
including A-to-B-to-A reuse. A retry therefore requires a new reviewed approval
id and newer sequence rather than a mutable `operation.retry` policy.

Before opening the approval, prove that backups and state checks required by
the application hooks pass and that no previous operation is active. After the
exact operation is terminal, verify Application sync and health, deployments,
sessions, model catalog, router drain, and consistent SQLite backup checks.
Then merge a second GitOps change that restores `state-writer-lease: inactive`
and removes all four approval annotations. Never leave an active approval on
the Application.
