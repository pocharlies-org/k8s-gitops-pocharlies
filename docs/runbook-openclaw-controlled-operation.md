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

Do not use the Argo UI or `argocd app sync` for this protected Application:
Argo 3.4 adds source, strategy, and retry fields that the policy deliberately
rejects. Submit a raw merge patch containing only `operation.sync.revision`,
`operation.sync.prune`, the exact GitOps `operation.sync.syncOptions`, and the
two `operation.info` items. Use a ten-minute TokenRequest for the dedicated
executor and a clean temporary kubeconfig, never a long-lived ServiceAccount
secret. Supplying `--token` to the normal admin kubeconfig is unsafe because its
client certificate can still authenticate the request as `system:admin`.

```sh
set -eu
umask 077
BASE_CONTEXT="$(kubectl config current-context)"
EXEC_DIR="$(mktemp -d)"
EXEC_KUBECONFIG="$EXEC_DIR/kubeconfig"
EXEC_CA="$EXEC_DIR/ca.crt"
TOKEN=''
PATCH=''
cleanup() {
  unset TOKEN PATCH
  rm -rf "$EXEC_DIR"
}
trap cleanup EXIT HUP INT TERM

SERVER_URL="$(kubectl --context="$BASE_CONTEXT" config view \
  --minify --raw -o jsonpath='{.clusters[0].cluster.server}')"
kubectl --context="$BASE_CONTEXT" config view --minify --flatten --raw \
  -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' \
  | base64 -d >"$EXEC_CA"
TOKEN="$(kubectl --context="$BASE_CONTEXT" -n argocd create token \
  openclaw-operation-executor --duration=10m)"

kubectl config --kubeconfig="$EXEC_KUBECONFIG" set-cluster target \
  --server="$SERVER_URL" --certificate-authority="$EXEC_CA" --embed-certs=true
kubectl config --kubeconfig="$EXEC_KUBECONFIG" set-credentials executor \
  --token="$TOKEN"
kubectl config --kubeconfig="$EXEC_KUBECONFIG" set-context executor \
  --cluster=target --user=executor --namespace=argocd
kubectl config --kubeconfig="$EXEC_KUBECONFIG" use-context executor
chmod 600 "$EXEC_KUBECONFIG" "$EXEC_CA"

IDENTITY="$(kubectl --kubeconfig="$EXEC_KUBECONFIG" auth whoami \
  -o jsonpath='{.status.userInfo.username}')"
test "$IDENTITY" = \
  'system:serviceaccount:argocd:openclaw-operation-executor'

APP_JSON="$(kubectl --kubeconfig="$EXEC_KUBECONFIG" -n argocd get \
  application openclaw-qwen36 -o json)"
PATCH="$(printf '%s' "$APP_JSON" | jq -ce '
  .metadata.annotations as $a
  | if $a["operations.pocharlies.org/state-writer-lease"] != "active"
    then error("writer lease is not active") else . end
  | if ($a["operations.pocharlies.org/approved-revision"] | test("^[0-9a-f]{40}$")) | not
    then error("approved revision is invalid") else . end
  | if ($a["operations.pocharlies.org/approval-sequence"] | test("^[0-9]{14}$")) | not
    then error("approval sequence is invalid") else . end
  | {
      operation: {
        sync: {
          revision: $a["operations.pocharlies.org/approved-revision"],
          prune: ($a["operations.pocharlies.org/approved-prune"] == "true"),
          syncOptions: .spec.syncPolicy.syncOptions
        },
        info: [
          {name: "approval-id", value: $a["operations.pocharlies.org/approval-id"]},
          {name: "approval-sequence", value: $a["operations.pocharlies.org/approval-sequence"]}
        ]
      }
    }
')"

kubectl --kubeconfig="$EXEC_KUBECONFIG" -n argocd patch \
  application openclaw-qwen36 --type=merge --dry-run=server -p "$PATCH"
kubectl --kubeconfig="$EXEC_KUBECONFIG" -n argocd patch \
  application openclaw-qwen36 --type=merge -p "$PATCH"
```

The dry-run must succeed only during the reviewed window. Submit the
byte-identical patch once; a second update is denied while the operation is in
flight.

Only the Argo application controller may change the Application spec, metadata,
status, an in-flight operation, or delete the Application. The Argo server has
one narrow exception: it may change a running operation to `Terminating`. This
prevents two-request spec overrides, deletion-approval/finalizer bypasses, and
protects the status-backed consumption ledger.

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
