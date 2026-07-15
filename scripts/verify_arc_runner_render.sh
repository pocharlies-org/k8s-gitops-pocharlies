#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="${ROOT}/infra/arc.yaml"
CHART="oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set"
CHART_VERSION="0.14.1"

command -v helm >/dev/null 2>&1 || {
  echo "helm is required to verify the ARC render" >&2
  exit 1
}
python3 -c 'import yaml' >/dev/null 2>&1 || {
  echo "PyYAML is required to verify the ARC render" >&2
  exit 1
}

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

python3 - "${MANIFEST}" "${tmpdir}" <<'PY'
from pathlib import Path
import sys

import yaml


manifest = Path(sys.argv[1])
output = Path(sys.argv[2])
applications = {
    document["metadata"]["name"]: document
    for document in yaml.safe_load_all(manifest.read_text(encoding="utf-8"))
    if isinstance(document, dict) and document.get("kind") == "Application"
}

for name in ("arc-openclaw", "arc-k8s"):
    application = applications[name]
    source = application["spec"]["source"]
    assert source["targetRevision"] == "0.14.1"
    values_text = source["helm"]["values"]
    values = yaml.safe_load(values_text)
    assert "containerMode" not in values, (
        f"{name}: containerMode must stay unset when the pod template is customized"
    )
    (output / f"{name}.values.yaml").write_text(values_text, encoding="utf-8")
PY

for release in arc-openclaw arc-k8s; do
  helm template "${release}" "${CHART}" \
    --version "${CHART_VERSION}" \
    --namespace arc-runners \
    --values "${tmpdir}/${release}.values.yaml" \
    > "${tmpdir}/${release}.rendered.yaml"
done

python3 - "${tmpdir}" <<'PY'
from pathlib import Path
import sys

import yaml


root = Path(sys.argv[1])
expected_selector = {"kubernetes.io/arch": "amd64", "node-pool": "ks5-nvme"}
expected_antiaffinity_labels = {
    "app.kubernetes.io/component": "runner",
    "app.kubernetes.io/part-of": "gha-runner-scale-set",
}


def rendered_runner_set(release: str) -> dict:
    documents = [
        document
        for document in yaml.safe_load_all(
            (root / f"{release}.rendered.yaml").read_text(encoding="utf-8")
        )
        if isinstance(document, dict)
    ]
    matches = [document for document in documents if document.get("kind") == "AutoscalingRunnerSet"]
    assert len(matches) == 1, f"{release}: expected one AutoscalingRunnerSet, got {len(matches)}"
    return matches[0]


def validate_common(release: str, expected_max: int) -> tuple[dict, dict]:
    runner_set = rendered_runner_set(release)
    assert runner_set["spec"]["maxRunners"] == expected_max
    pod_spec = runner_set["spec"]["template"]["spec"]
    assert pod_spec["nodeSelector"] == expected_selector
    assert "kubernetes.io/hostname" not in pod_spec["nodeSelector"]

    terms = pod_spec["affinity"]["podAntiAffinity"][
        "requiredDuringSchedulingIgnoredDuringExecution"
    ]
    assert len(terms) == 1
    assert terms[0]["topologyKey"] == "kubernetes.io/hostname"
    assert terms[0]["labelSelector"]["matchLabels"] == expected_antiaffinity_labels
    return runner_set, pod_spec


_, openclaw_spec = validate_common("arc-openclaw", 1)
assert [container["name"] for container in openclaw_spec["containers"]] == ["runner"]
assert openclaw_spec.get("initContainers", []) == []
assert openclaw_spec.get("volumes", []) == []
openclaw_runner = openclaw_spec["containers"][0]
assert not openclaw_runner.get("securityContext", {}).get("privileged", False)
assert "DOCKER_HOST" not in {item["name"] for item in openclaw_runner.get("env", [])}

_, shared_spec = validate_common("arc-k8s", 2)
assert [container["name"] for container in shared_spec["containers"]] == ["runner"]
assert [container["name"] for container in shared_spec["initContainers"]] == [
    "init-dind-externals",
    "dind",
]
externals_init = shared_spec["initContainers"][0]
assert externals_init["command"] == ["cp"]
assert externals_init["args"] == [
    "-r",
    "/home/runner/externals/.",
    "/home/runner/tmpDir/",
]

shared_runner = shared_spec["containers"][0]
runner_env = {item["name"]: item.get("value") for item in shared_runner["env"]}
assert runner_env["DOCKER_HOST"] == "unix:///var/run/docker.sock"

dind = shared_spec["initContainers"][1]
assert dind["restartPolicy"] == "Always"
assert dind["securityContext"]["privileged"] is True
assert dind["resources"] == {
    "requests": {"cpu": "250m", "memory": "512Mi"},
    "limits": {"cpu": "2", "memory": "4Gi"},
}
assert {volume["name"] for volume in shared_spec["volumes"]} == {
    "work",
    "dind-sock",
    "dind-externals",
}

print("ARC runner render contract: OK")
PY
