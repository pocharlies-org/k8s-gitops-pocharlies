#!/usr/bin/env bash
set -euo pipefail

# Fixed-scope executor for the manual openclaw-synapse Application sync. The
# default is a server-side dry run. --execute performs exactly one persisted
# merge PATCH using only the short-lived dedicated executor identity.
MODE="dry-run-only"
REVISION=''
REASON=''
usage() {
  printf 'Usage: %s --revision <40-hex> --reason <nonempty> [--dry-run-only|--execute]\n' "$0" >&2
}
while (( $# > 0 )); do
  case "$1" in
    --revision)
      [[ $# -ge 2 ]] || { usage; exit 64; }
      REVISION="$2"
      shift 2
      ;;
    --reason)
      [[ $# -ge 2 ]] || { usage; exit 64; }
      REASON="$2"
      shift 2
      ;;
    --dry-run-only)
      MODE="dry-run-only"
      shift
      ;;
    --execute)
      MODE="execute"
      shift
      ;;
    *)
      usage
      exit 64
      ;;
  esac
done

[[ "$REVISION" =~ ^[0-9a-f]{40}$ ]] || {
  printf 'Revision must be exactly 40 lowercase hexadecimal characters.\n' >&2
  exit 64
}
[[ "$REASON" =~ [^[:space:]] ]] || {
  printf 'Reason must be nonempty.\n' >&2
  exit 64
}

for command in kubectl jq base64; do
  command -v "$command" >/dev/null || {
    printf 'Missing required command: %s\n' "$command" >&2
    exit 69
  }
done

readonly APP_NAMESPACE="argocd"
readonly APP_NAME="openclaw-synapse"
readonly EXECUTOR_SA="openclaw-operation-executor"
readonly EXECUTOR_IDENTITY="system:serviceaccount:argocd:${EXECUTOR_SA}"

umask 077
BASE_CONTEXT="${BASE_CONTEXT:-$(kubectl config current-context)}"
EXEC_DIR="$(mktemp -d)"
EXEC_KUBECONFIG="${EXEC_DIR}/kubeconfig"
EXEC_CA="${EXEC_DIR}/ca.crt"
EXEC_TOKEN="${EXEC_DIR}/token"
PATCH=''
cleanup() {
  unset PATCH
  rm -rf "$EXEC_DIR"
}
trap cleanup EXIT HUP INT TERM

SERVER_URL="$(kubectl --context="$BASE_CONTEXT" config view \
  --minify --raw -o jsonpath='{.clusters[0].cluster.server}')"
kubectl --context="$BASE_CONTEXT" config view --minify --flatten --raw \
  -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' \
  | base64 -d >"$EXEC_CA"
kubectl --context="$BASE_CONTEXT" -n "$APP_NAMESPACE" create token \
  "$EXECUTOR_SA" --duration=10m >"$EXEC_TOKEN"

# Build the protected kubeconfig without ever placing the bearer token in argv.
jq -n --arg server "$SERVER_URL" --arg ca "$EXEC_CA" \
  --arg namespace "$APP_NAMESPACE" --rawfile token "$EXEC_TOKEN" '{
    apiVersion: "v1",
    kind: "Config",
    clusters: [{name: "target", cluster: {
      server: $server,
      "certificate-authority": $ca
    }}],
    users: [{name: "executor", user: {token: ($token | rtrimstr("\n"))}}],
    contexts: [{name: "executor", context: {
      cluster: "target",
      user: "executor",
      namespace: $namespace
    }}],
    "current-context": "executor"
  }' >"$EXEC_KUBECONFIG"
chmod 600 "$EXEC_KUBECONFIG" "$EXEC_CA" "$EXEC_TOKEN"

IDENTITY="$(kubectl --kubeconfig="$EXEC_KUBECONFIG" auth whoami \
  -o jsonpath='{.status.userInfo.username}')"
if [[ "$IDENTITY" != "$EXECUTOR_IDENTITY" ]]; then
  printf 'Unexpected executor identity: %s\n' "$IDENTITY" >&2
  exit 77
fi

APP_JSON="$(kubectl --kubeconfig="$EXEC_KUBECONFIG" -n "$APP_NAMESPACE" get \
  application "$APP_NAME" -o json)"
PATCH="$(printf '%s' "$APP_JSON" | jq -ce \
  --arg revision "$REVISION" --arg reason "$REASON" '
    if has("operation")
      then error("an operation is already present") else . end
    | if ((.metadata.resourceVersion // "") | test("^[0-9]+$")) | not
      then error("resourceVersion is missing or invalid") else . end
    | (.status.operationState.phase? // null) as $phase
    | if ($phase == "Running" or $phase == "Terminating")
      then error("an operation is already in flight") else . end
    | {
        metadata: {resourceVersion: .metadata.resourceVersion},
        operation: {
          initiatedBy: {},
          info: [{name: "reason", value: $reason}],
          sync: {
            revision: $revision,
            syncOptions: ["CreateNamespace=true", "ServerSideApply=true"]
          },
          retry: {}
        },
        status: {operationState: null}
      }
  ')"

# Server-evaluate the exact bytes that execution would persist.
DRY_RUN_RESULT="$(kubectl --kubeconfig="$EXEC_KUBECONFIG" \
  -n "$APP_NAMESPACE" patch application "$APP_NAME" --type=merge \
  --dry-run=server -p "$PATCH" -o json)"
printf '%s' "$DRY_RUN_RESULT" | jq -e --arg revision "$REVISION" '
  .operation.sync.revision == $revision
  and (.status | has("operationState") | not)
' >/dev/null

if [[ "$MODE" == "dry-run-only" ]]; then
  printf 'PASS: openclaw-synapse manual sync patch admitted by server dry-run; no object changed.\n'
  exit 0
fi

# This is the only persisted request. It always uses the ephemeral SA kubeconfig.
RESULT="$(kubectl --kubeconfig="$EXEC_KUBECONFIG" \
  -n "$APP_NAMESPACE" patch application "$APP_NAME" --type=merge \
  -p "$PATCH" -o json)"
printf '%s' "$RESULT" | jq -e --arg revision "$REVISION" '
  .operation.sync.revision == $revision
  and (.status | has("operationState") | not)
' >/dev/null
printf 'PASS: openclaw-synapse manual sync submitted at revision %s.\n' "$REVISION"
