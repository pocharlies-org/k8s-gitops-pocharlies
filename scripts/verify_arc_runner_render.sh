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

if not __debug__:
    raise SystemExit("ARC render validation requires Python assertions enabled")

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

if not __debug__:
    raise SystemExit("ARC render validation requires Python assertions enabled")

root = Path(sys.argv[1])
runner_image = "ghcr.io/actions/actions-runner:2.337.0@sha256:e5496277be5d09bc968b3d64911b74e219ac4a3f2edce956a3ecf9271bea1ef4"
dind_image = "docker.io/library/docker:29.7.1-dind@sha256:e8faad5a8dc5279dff929afc5449f2791736912fff9f99351d742db2fad01b4c"
expected_selector = {"kubernetes.io/arch": "amd64"}
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


def validate_common(
    release: str, expected_max: int, *, edge_fallback: bool
) -> tuple[dict, dict]:
    runner_set = rendered_runner_set(release)
    assert runner_set["spec"]["maxRunners"] == expected_max
    pod_spec = runner_set["spec"]["template"]["spec"]
    assert pod_spec["nodeSelector"] == expected_selector
    assert "kubernetes.io/hostname" not in pod_spec["nodeSelector"]

    ks5_term = {
        "matchExpressions": [
            {"key": "node-pool", "operator": "In", "values": ["ks5-nvme"]}
        ]
    }
    if edge_fallback:
        # arc-openclaw: KS5 fijado, con fallback a edge (sauvage).
        node_affinity = pod_spec["affinity"]["nodeAffinity"]
        edge_term = {
            "matchExpressions": [
                {"key": "role", "operator": "In", "values": ["edge"]}
            ]
        }
        assert node_affinity["requiredDuringSchedulingIgnoredDuringExecution"] == {
            "nodeSelectorTerms": [ks5_term, edge_term]
        }
        node_preferences = node_affinity[
            "preferredDuringSchedulingIgnoredDuringExecution"
        ]
        assert node_preferences == [{"weight": 100, "preference": ks5_term}]
        assert {
            "effect": "NoSchedule",
            "key": "role",
            "operator": "Equal",
            "value": "edge",
        } in pod_spec["tolerations"]
    else:
        # arc-k8s (2026-09-22, Dani): sigue sin nodeAffinity — no se fijan
        # hostnames —, pero YA NO tolera role=edge, y por eso no aterriza en
        # sauvage: es el unico nodo con ese taint y su md3 esta al 100 %
        # (medido: arrancar un pod alli no termino en 120 s, contra 0,34 s en
        # ks5-cp-1). Deroga el "scheduling libre" del 16-09.
        assert "nodeAffinity" not in pod_spec["affinity"]
        assert {
            "effect": "NoSchedule",
            "key": "role",
            "operator": "Equal",
            "value": "edge",
        } not in pod_spec["tolerations"]

    pod_anti_affinity = pod_spec["affinity"]["podAntiAffinity"]
    assert "requiredDuringSchedulingIgnoredDuringExecution" not in pod_anti_affinity
    terms = pod_anti_affinity["preferredDuringSchedulingIgnoredDuringExecution"]
    assert len(terms) == 1
    assert terms[0]["weight"] == 100
    pod_affinity_term = terms[0]["podAffinityTerm"]
    assert pod_affinity_term["topologyKey"] == "kubernetes.io/hostname"
    assert pod_affinity_term["labelSelector"]["matchLabels"] == expected_antiaffinity_labels
    return runner_set, pod_spec


def scheduler_eligible(pod_spec: dict, labels: dict[str, str]) -> bool:
    if any(labels.get(key) != value for key, value in pod_spec["nodeSelector"].items()):
        return False
    # Un nodo con taint role=edge (hoy solo sauvage) exige tolerarlo. Antes esto
    # no se modelaba y la matriz daba sauvage=True para cualquier pool: al dejar
    # de tolerarlo, el render habria seguido "verde" mintiendo.
    if labels.get("role") == "edge" and not any(
        t.get("key") == "role" and t.get("value") == "edge"
        for t in pod_spec.get("tolerations", [])
    ):
        return False
    node_affinity = pod_spec["affinity"].get("nodeAffinity")
    if node_affinity is None:
        # Sin nodeAffinity (arc-k8s): acotan el nodeSelector (arch) y el taint
        # de arriba. No se fija hostname a proposito.
        return True
    terms = node_affinity["requiredDuringSchedulingIgnoredDuringExecution"][
        "nodeSelectorTerms"
    ]
    return any(
        all(
            expression["operator"] == "In"
            and labels.get(expression["key"]) in expression["values"]
            for expression in term["matchExpressions"]
        )
        for term in terms
    )


_, openclaw_spec = validate_common("arc-openclaw", 2, edge_fallback=True)
assert [container["name"] for container in openclaw_spec["containers"]] == ["runner"]
assert openclaw_spec.get("initContainers", []) == []
assert openclaw_spec.get("volumes", []) == []
openclaw_runner = openclaw_spec["containers"][0]
assert openclaw_runner["image"] == runner_image
assert openclaw_runner["imagePullPolicy"] == "IfNotPresent"
assert not openclaw_runner.get("securityContext", {}).get("privileged", False)
assert "DOCKER_HOST" not in {item["name"] for item in openclaw_runner.get("env", [])}

_, shared_spec = validate_common("arc-k8s", 16, edge_fallback=False)

eligibility_matrix = {
    "ks5": {"kubernetes.io/arch": "amd64", "node-pool": "ks5-nvme"},
    "sauvage": {"kubernetes.io/arch": "amd64", "role": "edge"},
    "ubuntu-gpu": {
        "kubernetes.io/arch": "amd64",
        "pool": "dev",
        "nvidia.com/gpu.present": "true",
    },
    "arm-gpu": {
        "kubernetes.io/arch": "arm64",
        "role": "edge",
        "nvidia.com/gpu.present": "true",
    },
}
# arc-k8s: elegible en los amd64 SANOS. sauvage queda fuera desde 2026-09-22 por
# no tolerar su taint role=edge (ver validate_common).
expected_eligibility = {
    "arc-openclaw": {
        "ks5": True,
        "sauvage": True,
        "ubuntu-gpu": False,
        "arm-gpu": False,
    },
    "arc-k8s": {
        "ks5": True,
        "sauvage": False,
        "ubuntu-gpu": True,
        "arm-gpu": False,
    },
}
for release, runner_spec in (
    ("arc-openclaw", openclaw_spec),
    ("arc-k8s", shared_spec),
):
    for case, labels in eligibility_matrix.items():
        assert scheduler_eligible(runner_spec, labels) is expected_eligibility[
            release
        ][case], (release, case)

assert [container["name"] for container in shared_spec["containers"]] == ["runner"]
assert [container["name"] for container in shared_spec["initContainers"]] == [
    "init-dind-externals",
    "dind",
]
externals_init = shared_spec["initContainers"][0]
assert externals_init["image"] == runner_image
assert externals_init["imagePullPolicy"] == "IfNotPresent"
assert externals_init["command"] == ["cp"]
assert externals_init["args"] == [
    "-r",
    "/home/runner/externals/.",
    "/home/runner/tmpDir/",
]
assert externals_init["resources"] == {
    "requests": {"cpu": "5m", "memory": "32Mi"},
    "limits": {"cpu": "100m", "memory": "128Mi"},
}

shared_runner = shared_spec["containers"][0]
assert shared_runner["image"] == runner_image
assert shared_runner["imagePullPolicy"] == "IfNotPresent"
runner_env = {item["name"]: item.get("value") for item in shared_runner["env"]}
assert runner_env["DOCKER_HOST"] == "unix:///var/run/docker.sock"
assert shared_runner["resources"] == {
    "requests": {"cpu": "100m", "memory": "1Gi"},
    "limits": {"cpu": "2", "memory": "4Gi"},
}

dind = shared_spec["initContainers"][1]
assert dind["image"] == dind_image
assert dind["imagePullPolicy"] == "IfNotPresent"
# 2026-09-16: uploads de registry en paralelo (sin --max-concurrent-uploads=1).
# 2026-09-17: --mtu=1230 para igualar la MTU de la red de pods. Sin el, dockerd
# deja el bridge en 1500 y las transferencias grandes del build se cuelgan en
# los nodos cuyo egress no lo rescata por PMTU discovery.
assert dind["args"] == [
    "dockerd",
    "--host=unix:///var/run/docker.sock",
    "--group=$(DOCKER_GROUP_GID)",
    "--mtu=1230",
]
assert dind["restartPolicy"] == "Always"
assert dind["securityContext"]["privileged"] is True
assert dind["resources"] == {
    "requests": {"cpu": "50m", "memory": "512Mi"},
    "limits": {"cpu": "2", "memory": "4Gi"},
}
assert {volume["name"] for volume in shared_spec["volumes"]} == {
    "work",
    "dind-sock",
    "dind-externals",
}

print("ARC runner render contract: OK")
PY
