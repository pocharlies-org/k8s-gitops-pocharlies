#!/usr/bin/env bash
# Renders the ArgoCD chart with argocd/values.yaml and asserts that the
# application-controller is schedulable on the current cluster.
#
# Regression guarded: pinning global.nodeSelector to kubernetes.io/hostname=ubuntu
# produced a selector that intersected the live objects' node-pool=ks5-nvme key,
# matching zero nodes and leaving argocd-application-controller-0 Pending with
# "0/7 nodes are available: ... didn't match Pod's node affinity/selector".
#
# Usage: argocd/tests/verify-scheduling.sh
set -euo pipefail

CHART_VERSION="9.5.14"   # matches the deployed release (helm -n argocd list)
VALUES="$(cd "$(dirname "$0")/.." && pwd)/values.yaml"

rendered="$(mktemp)"
trap 'rm -f "${rendered}"' EXIT

helm template argocd argo-cd \
  --repo https://argoproj.github.io/argo-helm \
  --version "${CHART_VERSION}" \
  --namespace argocd \
  --values "${VALUES}" >"${rendered}"

python3 - "${rendered}" <<'PY'
import sys, yaml

with open(sys.argv[1]) as fh:
    documents = [document for document in yaml.safe_load_all(fh) if document]

def resource(kind, name):
    return next(
        document
        for document in documents
        if document.get("kind") == kind and document.get("metadata", {}).get("name") == name
    )

sts = resource("StatefulSet", "argocd-application-controller")
spec = sts["spec"]["template"]["spec"]
selector = spec.get("nodeSelector", {}) or {}
mem = spec["containers"][0]["resources"]["limits"]["memory"]
redis = resource("Deployment", "argocd-redis")
redis_resources = redis["spec"]["template"]["spec"]["containers"][0].get("resources", {})
redis_mem = redis_resources.get("limits", {}).get("memory")

print("--- rendered controller nodeSelector")
for k, v in sorted(selector.items()):
    print(f"    {k}: {v}")
print(f"--- rendered controller memory limit: {mem}")
print(f"--- rendered Redis memory limit: {redis_mem}")

failures = []
if selector.get("node-pool") != "ks5-nvme":
    failures.append("controller must select the ks5-nvme pool")
if "kubernetes.io/hostname" in selector:
    failures.append("controller must not be pinned to a single hostname")
if mem != "2Gi":
    failures.append(f"controller memory limit must stay 2Gi, got {mem!r}")
if redis_mem != "256Mi":
    failures.append(f"Redis memory limit must be 256Mi, got {redis_mem!r}")

for f in failures:
    print(f"FAIL: {f}", file=sys.stderr)
sys.exit(1 if failures else 0)
PY

# The selected label must exist on at least one schedulable node. Skipped when
# no cluster is reachable (e.g. CI without kubeconfig).
if command -v kubectl >/dev/null 2>&1 && kubectl get nodes >/dev/null 2>&1; then
  matching="$(kubectl get nodes -l node-pool=ks5-nvme --no-headers 2>/dev/null | wc -l)"
  echo "--- nodes matching node-pool=ks5-nvme: ${matching}"
  if [[ "${matching}" -lt 1 ]]; then
    echo "FAIL: no node carries node-pool=ks5-nvme" >&2
    exit 1
  fi
else
  echo "--- no cluster reachable; skipped live node check"
fi

echo "RESULT: PASS"
