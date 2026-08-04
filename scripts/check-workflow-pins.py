#!/usr/bin/env python3
"""Reject mutable third-party actions in every shared workflow."""

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
IMMUTABLE_REF = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")

violations: list[str] = []


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def action_uses(value, path=""):
    if isinstance(value, dict):
        for key, nested in value.items():
            current = f"{path}.{key}" if path else str(key)
            if key == "uses" and isinstance(nested, str):
                yield current, nested
            yield from action_uses(nested, current)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from action_uses(nested, f"{path}[{index}]")

# Guard the parser itself: inline YAML maps were the regression that a
# line-oriented scanner missed.
inline_mutants = (
    "jobs:\n  test:\n    steps:\n      - {uses: actions/checkout@v7}\n",
    'jobs:\n  test:\n    steps:\n      - {"uses": actions/checkout@v7}\n',
    "jobs:\n  test:\n    steps:\n      - {uses : actions/checkout@v7}\n",
)
for mutant in inline_mutants:
    require(
        [target for _path, target in action_uses(yaml.safe_load(mutant))]
        == ["actions/checkout@v7"],
        "uses parser self-test failed",
    )

workflows = sorted({*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")})
for workflow in workflows:
    text = workflow.read_text(encoding="utf-8")
    document = yaml.safe_load(text)
    for path, target in action_uses(document):
        if target.startswith("./"):
            continue
        if not IMMUTABLE_REF.fullmatch(target):
            violations.append(f"{workflow.relative_to(ROOT)}:{path}: {target}")

require(not violations, "mutable workflow dependencies:\n" + "\n".join(violations))

ci_workflow = (WORKFLOWS / "reusable-ci.yml").read_text(encoding="utf-8")
deploy_workflow = (WORKFLOWS / "reusable-deploy-stg.yml").read_text(encoding="utf-8")
for digest in (
    "6703a3a70a0c47cf0b37694030b54f1175a9dfeb17b3818b623ed58b9dbc2a77",
    "95f14e87aa28c09d5941f11bd024c1d02fdc0303ccaa23f61cef67bc92619d73",
):
    require(digest in ci_workflow, f"missing CI tool checksum: {digest}")
require("sha256sum --check --strict" in ci_workflow, "CI downloads are not checksum verified")
require("repository: ${{ job.workflow_repository }}" in ci_workflow, "checker repository is not workflow-bound")
require("ref: ${{ job.workflow_sha }}" in ci_workflow, "checker ref is not workflow-SHA-bound")
checker_checkout = ci_workflow.split("      - name: Check out the contract checker", 1)[1].split(
    "      - name: Enforce the contract rules", 1
)[0]
require("persist-credentials: false" in checker_checkout, "contract checker checkout persists credentials")
require(ci_workflow.count("actions/setup-python@e797f83bcb11b83ae66e0230d6156d7c80228e7c") == 2, "CI Python runtime is not pinned")
require(ci_workflow.count("python-version: \"3.11.14\"") == 2, "CI Python version is not exact")
require(ci_workflow.count("--require-hashes") == 2, "CI Python dependencies are not hash-locked")
for digest in (
    "b8bb0864c5a28024fac8a632c443c87c5aa6f215c0b126c449ae1a150412f31d",
    "a0d503e138a4c123b27490a4f7beda6a01c6f288df0e4a8b79c7eb0dc7b4cc08",
    "364f0d79e81409f591e323725e6a9f4504c8699ddf2d7263d8d2b539cd66a583",
):
    require(digest in ci_workflow, f"missing CI Python dependency checksum: {digest}")
require("pip install --quiet --upgrade pip" not in ci_workflow, "mutable pip upgrade is forbidden")
require("pip install --quiet pyyaml" not in ci_workflow, "mutable PyYAML install is forbidden")
require(ci_workflow.count("version=v24.19.0") == 2, "CI Node runtime is not exact")
for digest in (
    "14b342e71204f811bde6153be8e04b62aef63c236fef92b55f9c83154b409647",
    "01443c1e1a29e531ccad5a46fefa6df490d2189c49f7955904aecdbb0fe86fdc",
):
    require(ci_workflow.count(digest) == 2, f"CI Node checksum is not pinned: {digest}")
require("6703a3a70a0c47cf0b37694030b54f1175a9dfeb17b3818b623ed58b9dbc2a77" in deploy_workflow, "deploy kustomize checksum missing")
require("sha256sum --check --strict" in deploy_workflow, "deploy downloads are not checksum verified")
for buildx_marker in (
    "BUILDX_VERSION: v0.36.0",
    "BUILDKIT_IMAGE: moby/buildkit@sha256:2f5adac4ecd194d9f8c10b7b5d7bceb5186853db1b26e5abd3a657af0b7e26ec",
    "07823fdfcd82a41be90155a8b16876c1a780a6462de805a9f3f63b3119ccfb99",
    "70382de03915c07c488ae4ddc4f7e169ee978f953e754ecfce110ba017e0132b",
):
    require(buildx_marker in deploy_workflow, f"deploy Buildx toolchain is not pinned: {buildx_marker}")
require("docker/setup-buildx-action@" not in deploy_workflow, "deploy Buildx action download is not content-verified")
require(deploy_workflow.count("version=v24.19.0") == 1, "deploy Node runtime is not exact")
for digest in (
    "14b342e71204f811bde6153be8e04b62aef63c236fef92b55f9c83154b409647",
    "01443c1e1a29e531ccad5a46fefa6df490d2189c49f7955904aecdbb0fe86fdc",
):
    require(deploy_workflow.count(digest) == 1, f"deploy Node checksum is not pinned: {digest}")
require(deploy_workflow.startswith("name: Reusable Deploy Staging"), "unexpected deploy workflow")
require("permissions:\n  contents: read\n\njobs:" in deploy_workflow, "deploy workflow lacks read-only default permissions")
deploy_job = deploy_workflow.split("  deploy:", 1)[1].split("  notify:", 1)[0]
notify_job = deploy_workflow.split("  notify:", 1)[1]
require("permissions:\n      contents: write" in deploy_job, "deploy job lacks scoped write permission")
require("permissions:\n      contents: read" in notify_job, "notify job lacks read-only permission")
print("All third-party workflow dependencies are pinned to immutable commits")
