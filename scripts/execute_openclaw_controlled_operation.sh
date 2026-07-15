#!/usr/bin/env bash
set -euo pipefail

# Canonical executor for the reviewed OpenClaw operation window. The default is
# a server-side dry run. --execute performs exactly one persisted merge PATCH;
# that same patch atomically creates .operation and clears the previous terminal
# .status.operationState to avoid Argo CD issue #28701.
MODE="dry-run-only"
case "${1:-}" in
  "") ;;
  --dry-run-only) MODE="dry-run-only" ;;
  --execute) MODE="execute" ;;
  *)
    printf 'Usage: %s [--dry-run-only|--execute]\n' "$0" >&2
    exit 64
    ;;
esac

for command in kubectl jq base64; do
  command -v "$command" >/dev/null || {
    printf 'Missing required command: %s\n' "$command" >&2
    exit 69
  }
done

readonly APP_NAMESPACE="argocd"
readonly APP_NAME="openclaw-qwen36"
readonly EXECUTOR_SA="openclaw-operation-executor"
readonly EXECUTOR_IDENTITY="system:serviceaccount:argocd:${EXECUTOR_SA}"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PATCH_FILTER="${SCRIPT_DIR}/openclaw_operation_atomic_patch.jq"

umask 077
BASE_CONTEXT="${BASE_CONTEXT:-$(kubectl config current-context)}"
EXEC_DIR="$(mktemp -d)"
EXEC_KUBECONFIG="${EXEC_DIR}/kubeconfig"
EXEC_CA="${EXEC_DIR}/ca.crt"
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
TOKEN="$(kubectl --context="$BASE_CONTEXT" -n "$APP_NAMESPACE" create token \
  "$EXECUTOR_SA" --duration=10m)"

kubectl config --kubeconfig="$EXEC_KUBECONFIG" set-cluster target \
  --server="$SERVER_URL" --certificate-authority="$EXEC_CA" --embed-certs=true \
  >/dev/null
kubectl config --kubeconfig="$EXEC_KUBECONFIG" set-credentials executor \
  --token="$TOKEN" >/dev/null
kubectl config --kubeconfig="$EXEC_KUBECONFIG" set-context executor \
  --cluster=target --user=executor --namespace="$APP_NAMESPACE" >/dev/null
kubectl config --kubeconfig="$EXEC_KUBECONFIG" use-context executor >/dev/null
chmod 600 "$EXEC_KUBECONFIG" "$EXEC_CA"

IDENTITY="$(kubectl --kubeconfig="$EXEC_KUBECONFIG" auth whoami \
  -o jsonpath='{.status.userInfo.username}')"
if [[ "$IDENTITY" != "$EXECUTOR_IDENTITY" ]]; then
  printf 'Unexpected executor identity: %s\n' "$IDENTITY" >&2
  exit 77
fi

APP_JSON="$(kubectl --kubeconfig="$EXEC_KUBECONFIG" -n "$APP_NAMESPACE" get \
  application "$APP_NAME" -o json)"
PATCH="$(printf '%s' "$APP_JSON" | jq -ce -f "$PATCH_FILTER")"

# The server dry run compiles/evaluates RBAC and admission against the exact
# bytes that will be submitted. The resourceVersion in PATCH makes a race with
# controller reconciliation fail with Conflict rather than consuming stale
# approval/status state.
DRY_RUN_RESULT="$(kubectl --kubeconfig="$EXEC_KUBECONFIG" \
  -n "$APP_NAMESPACE" patch application "$APP_NAME" --type=merge \
  --dry-run=server -p "$PATCH" -o json)"
printf '%s' "$DRY_RUN_RESULT" | jq -e \
  --arg revision "$(printf '%s' "$PATCH" | jq -r '.operation.sync.revision')" '
    .operation.sync.revision == $revision
    and (.status | has("operationState") | not)
  ' >/dev/null

if [[ "$MODE" == "dry-run-only" ]]; then
  printf 'PASS: atomic OpenClaw operation patch admitted by server dry-run; no object changed.\n'
  exit 0
fi

# This is the only persisted request. Never split .operation creation and the
# operationState deletion into separate calls.
RESULT="$(kubectl --kubeconfig="$EXEC_KUBECONFIG" \
  -n "$APP_NAMESPACE" patch application "$APP_NAME" --type=merge \
  -p "$PATCH" -o json)"
printf '%s' "$RESULT" | jq -e \
  --arg revision "$(printf '%s' "$PATCH" | jq -r '.operation.sync.revision')" '
    .operation.sync.revision == $revision
    and (.status | has("operationState") | not)
  ' >/dev/null
printf 'PASS: reviewed OpenClaw operation atomically submitted at revision %s.\n' \
  "$(printf '%s' "$PATCH" | jq -r '.operation.sync.revision')"
