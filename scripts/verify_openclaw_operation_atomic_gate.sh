#!/usr/bin/env bash
set -euo pipefail

# Post-install harness for the two real oldObject states used by the policy.
# Every patch is a server-side dry run; no Application field is persisted.
# The default consume mode runs before the executor while a terminal state and
# an OPEN approval exist. --termination-only runs while an operation is Running
# and proves that argocd-server can change only phase to Terminating.
MODE="consume"
case "${1:-}" in
  ""|--consume-only) MODE="consume" ;;
  --termination-only) MODE="termination" ;;
  *)
    printf 'Usage: %s [--consume-only|--termination-only]\n' "$0" >&2
    exit 64
    ;;
esac

readonly APP_NAMESPACE="argocd"
readonly APP_NAME="openclaw-qwen36"
readonly POLICY="openclaw-operation-state-writer-gate"
readonly EXECUTOR_USER="system:serviceaccount:argocd:openclaw-operation-executor"
readonly ARGO_CONTROLLER_USER="system:serviceaccount:argocd:argocd-application-controller"
readonly ARGO_SERVER_USER="system:serviceaccount:argocd:argocd-server"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PATCH_FILTER="${SCRIPT_DIR}/openclaw_operation_atomic_patch.jq"
readonly DENIAL_TEXT="atomically clear any previous terminal operationState"

expect_denied() {
  local label="$1"
  shift
  local output
  local rc

  set +e
  output=$("$@" 2>&1)
  rc=$?
  set -e

  if [[ $rc -eq 0 ]]; then
    printf 'FAIL: %s unexpectedly passed admission\n%s\n' "$label" "$output" >&2
    return 1
  fi
  if [[ "$output" != *"$POLICY"* && "$output" != *"$DENIAL_TEXT"* &&
        "$output" != *"dedicated short-lived OpenClaw operation executor"* &&
        "$output" != *"trusted OpenClaw status"* ]]; then
    printf 'FAIL: %s failed outside the expected admission gate\n%s\n' \
      "$label" "$output" >&2
    return 1
  fi
  printf 'PASS denied: %s\n' "$label"
}

expect_allowed() {
  local label="$1"
  shift
  local output

  if ! output=$("$@" 2>&1); then
    printf 'FAIL: %s was not admitted\n%s\n' "$label" "$output" >&2
    return 1
  fi
  printf 'PASS allowed: %s\n' "$label"
}

expect_conflict() {
  local label="$1"
  shift
  local output
  local rc

  set +e
  output=$("$@" 2>&1)
  rc=$?
  set -e

  if [[ $rc -eq 0 ]]; then
    printf 'FAIL: %s unexpectedly ignored stale resourceVersion\n%s\n' \
      "$label" "$output" >&2
    return 1
  fi
  if [[ "$output" != *"Conflict"* &&
        "$output" != *"object has been modified"* ]]; then
    printf 'FAIL: %s did not fail with a resourceVersion conflict\n%s\n' \
      "$label" "$output" >&2
    return 1
  fi
  printf 'PASS conflict: %s\n' "$label"
}

kubectl get validatingadmissionpolicy "$POLICY" >/dev/null
kubectl get validatingadmissionpolicybinding "$POLICY" >/dev/null

APP_JSON="$(kubectl -n "$APP_NAMESPACE" get application "$APP_NAME" -o json)"

if [[ "$MODE" == "termination" ]]; then
  printf '%s' "$APP_JSON" | jq -e '
    has("operation")
    and .status.operationState.phase == "Running"
  ' >/dev/null || {
    printf 'FAIL: termination harness requires an active operation in Running phase\n' >&2
    exit 77
  }

  TERMINATE_PATCH="$(printf '%s' "$APP_JSON" | jq -ce '{
    metadata: {resourceVersion: .metadata.resourceVersion},
    status: {operationState: {phase: "Terminating"}}
  }')"
  HEALTH_TAMPER_PATCH="$(jq -nce --argjson base "$TERMINATE_PATCH" \
    --argjson app "$APP_JSON" '
      $base | .status.health = {
        status: (if $app.status.health.status == "Unknown" then "Healthy" else "Unknown" end),
        message: "admission dry-run probe"
      }
    ')"
  SYNC_TAMPER_PATCH="$(jq -nce --argjson base "$TERMINATE_PATCH" \
    --argjson app "$APP_JSON" '
      $base | .status.sync = {
        status: (if $app.status.sync.status == "Unknown" then "Synced" else "Unknown" end),
        revision: "admission-dry-run-probe"
      }
    ')"
  HISTORY_TAMPER_PATCH="$(jq -nce --argjson base "$TERMINATE_PATCH" \
    --argjson app "$APP_JSON" '
      $base | .status.history =
        (if ($app.status | has("history")) then null else [] end)
    ')"
  RESOURCES_TAMPER_PATCH="$(jq -nce --argjson base "$TERMINATE_PATCH" \
    --argjson app "$APP_JSON" '
      $base | .status.resources =
        (if ($app.status | has("resources")) then null else [] end)
    ')"
  MESSAGE_TAMPER_PATCH="$(jq -nce --argjson base "$TERMINATE_PATCH" \
    --argjson app "$APP_JSON" '
      $base | .status.operationState.message =
        (($app.status.operationState.message // "") + " [admission dry-run probe]")
    ')"
  SYNC_RESULT_TAMPER_PATCH="$(jq -nce --argjson base "$TERMINATE_PATCH" \
    --argjson app "$APP_JSON" '
      $base | .status.operationState.syncResult =
        (if ($app.status.operationState | has("syncResult"))
         then null else {revision: "admission-dry-run-probe"} end)
    ')"
  STARTED_AT_TAMPER_PATCH="$(jq -nce --argjson base "$TERMINATE_PATCH" \
    --argjson app "$APP_JSON" '
      $base | .status.operationState.startedAt =
        (if $app.status.operationState.startedAt == "2000-01-01T00:00:00Z"
         then "2000-01-02T00:00:00Z" else "2000-01-01T00:00:00Z" end)
    ')"
  FINISHED_AT_TAMPER_PATCH="$(jq -nce --argjson base "$TERMINATE_PATCH" \
    --argjson app "$APP_JSON" '
      $base | .status.operationState.finishedAt =
        (if $app.status.operationState.finishedAt == "2000-01-01T00:00:00Z"
         then "2000-01-02T00:00:00Z" else "2000-01-01T00:00:00Z" end)
    ')"
  RETRY_COUNT_TAMPER_PATCH="$(jq -nce --argjson base "$TERMINATE_PATCH" \
    --argjson app "$APP_JSON" '
      $base | .status.operationState.retryCount =
        (if $app.status.operationState.retryCount == 2147483647
         then 0 else 2147483647 end)
    ')"

  expect_allowed "argocd-server exact Running-to-Terminating transition" \
    kubectl --as="$ARGO_SERVER_USER" -n "$APP_NAMESPACE" \
    patch application "$APP_NAME" --type=merge --patch "$TERMINATE_PATCH" \
    --dry-run=server -o name

  expect_denied "argocd-server termination with health tamper" \
    kubectl --as="$ARGO_SERVER_USER" -n "$APP_NAMESPACE" \
    patch application "$APP_NAME" --type=merge --patch "$HEALTH_TAMPER_PATCH" \
    --dry-run=server -o name

  expect_denied "argocd-server termination with sync tamper" \
    kubectl --as="$ARGO_SERVER_USER" -n "$APP_NAMESPACE" \
    patch application "$APP_NAME" --type=merge --patch "$SYNC_TAMPER_PATCH" \
    --dry-run=server -o name

  expect_denied "argocd-server termination with history tamper" \
    kubectl --as="$ARGO_SERVER_USER" -n "$APP_NAMESPACE" \
    patch application "$APP_NAME" --type=merge --patch "$HISTORY_TAMPER_PATCH" \
    --dry-run=server -o name

  expect_denied "argocd-server termination with resources tamper" \
    kubectl --as="$ARGO_SERVER_USER" -n "$APP_NAMESPACE" \
    patch application "$APP_NAME" --type=merge --patch "$RESOURCES_TAMPER_PATCH" \
    --dry-run=server -o name

  expect_denied "argocd-server termination with message tamper" \
    kubectl --as="$ARGO_SERVER_USER" -n "$APP_NAMESPACE" \
    patch application "$APP_NAME" --type=merge --patch "$MESSAGE_TAMPER_PATCH" \
    --dry-run=server -o name

  expect_denied "argocd-server termination with syncResult tamper" \
    kubectl --as="$ARGO_SERVER_USER" -n "$APP_NAMESPACE" \
    patch application "$APP_NAME" --type=merge --patch "$SYNC_RESULT_TAMPER_PATCH" \
    --dry-run=server -o name

  expect_denied "argocd-server termination with startedAt tamper" \
    kubectl --as="$ARGO_SERVER_USER" -n "$APP_NAMESPACE" \
    patch application "$APP_NAME" --type=merge --patch "$STARTED_AT_TAMPER_PATCH" \
    --dry-run=server -o name

  expect_denied "argocd-server termination with finishedAt tamper" \
    kubectl --as="$ARGO_SERVER_USER" -n "$APP_NAMESPACE" \
    patch application "$APP_NAME" --type=merge --patch "$FINISHED_AT_TAMPER_PATCH" \
    --dry-run=server -o name

  expect_denied "argocd-server termination with retryCount tamper" \
    kubectl --as="$ARGO_SERVER_USER" -n "$APP_NAMESPACE" \
    patch application "$APP_NAME" --type=merge --patch "$RETRY_COUNT_TAMPER_PATCH" \
    --dry-run=server -o name

  printf 'All termination adversarial server-side dry-run checks passed. No object was changed.\n'
  exit 0
fi

printf '%s' "$APP_JSON" | jq -e '
  (.operation | not)
  and .status.operationState.phase as $phase
  | $phase == "Succeeded" or $phase == "Failed" or $phase == "Error"
' >/dev/null || {
  printf 'FAIL: harness requires no active operation and one terminal operationState\n' >&2
  exit 77
}

ATOMIC_PATCH="$(printf '%s' "$APP_JSON" | jq -ce -f "$PATCH_FILTER")"
STALE_CAS_PATCH="$(printf '%s' "$ATOMIC_PATCH" | jq -ce \
  '.metadata.resourceVersion = "1"')"
OPERATION_ONLY_PATCH="$(printf '%s' "$ATOMIC_PATCH" | jq -ce 'del(.status)')"
CLEAR_ONLY_PATCH="$(printf '%s' "$ATOMIC_PATCH" | jq -ce 'del(.operation)')"
RUNNING_REPLACEMENT_PATCH="$(printf '%s' "$ATOMIC_PATCH" | jq -ce \
  '.status.operationState = {phase: "Running"}')"
STATUS_TAMPER_PATCH="$(printf '%s' "$ATOMIC_PATCH" | jq -ce \
  '.status.health = {status: "Unknown", message: "admission dry-run probe"}')"

expect_allowed "dedicated executor atomic consume" \
  kubectl --as="$EXECUTOR_USER" -n "$APP_NAMESPACE" patch application "$APP_NAME" \
  --type=merge --patch "$ATOMIC_PATCH" --dry-run=server -o name

expect_conflict "dedicated executor stale resourceVersion CAS" \
  kubectl --as="$EXECUTOR_USER" -n "$APP_NAMESPACE" patch application "$APP_NAME" \
  --type=merge --patch "$STALE_CAS_PATCH" --dry-run=server -o name

expect_denied "operation-only stale-state retention" \
  kubectl --as="$EXECUTOR_USER" -n "$APP_NAMESPACE" patch application "$APP_NAME" \
  --type=merge --patch "$OPERATION_ONLY_PATCH" --dry-run=server -o name

expect_denied "terminal-state clear without approval consumption" \
  kubectl --as="$EXECUTOR_USER" -n "$APP_NAMESPACE" patch application "$APP_NAME" \
  --type=merge --patch "$CLEAR_ONLY_PATCH" --dry-run=server -o name

expect_denied "operationState replacement instead of deletion" \
  kubectl --as="$EXECUTOR_USER" -n "$APP_NAMESPACE" patch application "$APP_NAME" \
  --type=merge --patch "$RUNNING_REPLACEMENT_PATCH" --dry-run=server -o name

expect_denied "atomic consume with sibling status tamper" \
  kubectl --as="$EXECUTOR_USER" -n "$APP_NAMESPACE" patch application "$APP_NAME" \
  --type=merge --patch "$STATUS_TAMPER_PATCH" --dry-run=server -o name

expect_denied "Argo controller cannot impersonate operation executor" \
  kubectl --as="$ARGO_CONTROLLER_USER" -n "$APP_NAMESPACE" \
  patch application "$APP_NAME" --type=merge --patch "$ATOMIC_PATCH" \
  --dry-run=server -o name

printf 'All atomic operation adversarial server-side dry-run checks passed. No object was changed.\n'
