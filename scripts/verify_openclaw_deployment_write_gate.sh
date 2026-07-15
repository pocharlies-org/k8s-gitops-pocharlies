#!/usr/bin/env bash
set -euo pipefail

# Post-install adversarial harness. Every mutating request is a server-side dry
# run: this script never persists a Deployment change.
NAMESPACE="${NAMESPACE:-openclaw-qwen36}"
DEPLOYMENT="${DEPLOYMENT:-openclaw-qwen36-openclaw}"
SYNAPSE_NAMESPACE="${SYNAPSE_NAMESPACE:-openclaw-synapse}"
CONTROL_NAMESPACE="${CONTROL_NAMESPACE:-default}"
POLICY="openclaw-runtime-deployment-write-gate"
ARGO_USER="system:serviceaccount:argocd:argocd-application-controller"
DENIAL_TEXT="Direct writes to production OpenClaw Deployments"

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
  if [[ "$output" != *"$DENIAL_TEXT"* && "$output" != *"$POLICY"* ]]; then
    printf 'FAIL: %s failed outside the expected admission gate\n%s\n' "$label" "$output" >&2
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

kubectl get validatingadmissionpolicy "$POLICY" >/dev/null
kubectl get validatingadmissionpolicybinding "$POLICY" >/dev/null
kubectl -n "$NAMESPACE" get deployment "$DEPLOYMENT" >/dev/null

expect_denied "CREATE in production namespace" \
  kubectl -n "$NAMESPACE" create deployment namespace-only-write-gate-probe \
  --image=registry.k8s.io/pause:3.10 --dry-run=server -o name

expect_denied "direct metadata UPDATE" \
  kubectl -n "$NAMESPACE" patch deployment "$DEPLOYMENT" --type=merge \
  --patch '{"metadata":{"annotations":{"operations.pocharlies.org/admission-probe":"direct-update"}}}' \
  --dry-run=server -o name

expect_denied "kubectl rollout restart" \
  kubectl -n "$NAMESPACE" rollout restart "deployment/$DEPLOYMENT" \
  --dry-run=server -o name

expect_denied "scale subresource UPDATE" \
  kubectl -n "$NAMESPACE" scale "deployment/$DEPLOYMENT" --replicas=1 \
  --dry-run=server -o name

expect_denied "DELETE in production namespace" \
  kubectl -n "$NAMESPACE" delete "deployment/$DEPLOYMENT" \
  --dry-run=server --wait=false

expect_allowed "Argo application-controller UPDATE" \
  kubectl --as="$ARGO_USER" -n "$NAMESPACE" patch deployment "$DEPLOYMENT" \
  --type=merge \
  --patch '{"metadata":{"annotations":{"operations.pocharlies.org/admission-probe":"argo-update"}}}' \
  --dry-run=server -o name

# deployments/status is intentionally outside matchConstraints. This uses the
# caller's existing RBAC identity; a Forbidden here must be investigated as an
# RBAC failure, while a write-gate denial is a policy scope regression.
expect_allowed "deployment status subresource" \
  kubectl -n "$NAMESPACE" patch deployment "$DEPLOYMENT" --subresource=status \
  --type=merge --patch '{"status":{}}' --dry-run=server -o name

SYNAPSE_DEPLOYMENT="${SYNAPSE_DEPLOYMENT:-$(
  kubectl -n "$SYNAPSE_NAMESPACE" get deployment \
    -o jsonpath='{.items[0].metadata.name}'
)}"
if [[ -z "$SYNAPSE_DEPLOYMENT" ]]; then
  printf 'FAIL: no Deployment found in Synapse namespace %s\n' "$SYNAPSE_NAMESPACE" >&2
  exit 1
fi

expect_allowed "Synapse namespace UPDATE" \
  kubectl -n "$SYNAPSE_NAMESPACE" patch deployment "$SYNAPSE_DEPLOYMENT" \
  --type=merge \
  --patch '{"metadata":{"annotations":{"operations.pocharlies.org/admission-probe":"synapse-scope"}}}' \
  --dry-run=server -o name

expect_allowed "unrelated namespace CREATE" \
  kubectl -n "$CONTROL_NAMESPACE" create deployment openclaw-write-gate-control \
  --image=registry.k8s.io/pause:3.10 --dry-run=server -o name

printf 'All adversarial server-side dry-run checks passed. No object was changed.\n'
