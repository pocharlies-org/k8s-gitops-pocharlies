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


def run_blocks(value, path=""):
    if isinstance(value, dict):
        for key, nested in value.items():
            current = f"{path}.{key}" if path else str(key)
            if key == "run" and isinstance(nested, str):
                yield current, nested
            yield from run_blocks(nested, current)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from run_blocks(nested, f"{path}[{index}]")

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
    for path, script in run_blocks(document):
        require(
            "${{ inputs." not in script,
            f"workflow input interpolated directly into shell at {workflow.relative_to(ROOT)}:{path}",
        )

require(not violations, "mutable workflow dependencies:\n" + "\n".join(violations))

ci_workflow = (WORKFLOWS / "reusable-ci.yml").read_text(encoding="utf-8")
deploy_workflow = (WORKFLOWS / "reusable-deploy-stg.yml").read_text(encoding="utf-8")
central_ci_workflow = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
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
require("continue-on-error" not in checker_checkout, "contract checker checkout is fail-open")
require("exit 1" in ci_workflow.split("if [ ! -f \"$checker\" ]", 1)[1].split("fi", 1)[0], "missing contract checker is not fatal")
require("actions/setup-python@" not in ci_workflow + central_ci_workflow, "setup-python executes mutable bootstrap tooling")
require("pip install" not in ci_workflow + central_ci_workflow, "CI must not execute mutable pip installs")
require(ci_workflow.count("python3 -m zipfile -e") == 2, "CI hash-locked wheels are not extracted without pip")
require(ci_workflow.count("3.12|3.12.13) version=3.12.13") == 3, "CI Python runtime is not exact")
require(ci_workflow.count("5854aa6ec71cad00334d5065633c210b2e7feb40956767a59a91791cadcf0b79") == 3, "CI x86_64 Python runtime is not hash-locked")
require(ci_workflow.count("f226576b91491ffa5739aa85726521e9031f4d87f80627d64ed348ac77cb31e9") == 3, "CI arm64 Python runtime is not hash-locked")
require("corepack prepare" not in ci_workflow, "CI pnpm must not use a mutable Corepack download")
require('PNPM_VERSION: ${{ inputs.pnpm_version }}' in ci_workflow, "pnpm input is interpolated into shell code")
for digest in (
    "ea45517d5285d123eac02c3793505fa1fd6da90a2fc60d1e8d9e0c1e9292886ecfaff513f062b9d1cc8021bb8615033b1ac5bea3b2ee3fc165a6d7034bbe6b03",
    "cca3cea332ad254bb84145f966d19f4879615210346fc92c79a047f23a0d7b3cca3c3792f0076ba1f1831d277efbcf0a9119b31a9a60eca7fb3d6231f331ef72",
):
    require(digest in ci_workflow, f"CI pnpm tarball is not SHA-512 locked: {digest}")
for digest in (
    "b8bb0864c5a28024fac8a632c443c87c5aa6f215c0b126c449ae1a150412f31d",
    "a0d503e138a4c123b27490a4f7beda6a01c6f288df0e4a8b79c7eb0dc7b4cc08",
    "364f0d79e81409f591e323725e6a9f4504c8699ddf2d7263d8d2b539cd66a583",
):
    require(digest in ci_workflow, f"missing CI Python dependency checksum: {digest}")
require("b8bb0864c5a28024fac8a632c443c87c5aa6f215c0b126c449ae1a150412f31d" in central_ci_workflow, "central release gate PyYAML wheel is not hash-locked")
require("python3 -m zipfile -e" in central_ci_workflow, "central release gate does not extract its hash-locked wheel")
for digest in (
    "5854aa6ec71cad00334d5065633c210b2e7feb40956767a59a91791cadcf0b79",
    "f226576b91491ffa5739aa85726521e9031f4d87f80627d64ed348ac77cb31e9",
):
    require(digest in central_ci_workflow, f"central Python runtime is not hash-locked: {digest}")
require("npm', ['install'" not in ci_workflow and "npm install -g" not in ci_workflow, "notify executes mutable npm packages")
require("contracts: '${{ needs.contracts.result }}'" in ci_workflow, "contract failure is omitted from notification")
require(ci_workflow.count("22|22.23.2) version=v22.23.2") == 2, "CI Node 22 runtime is not exact")
require(ci_workflow.count("24|24.19.0) version=v24.19.0") == 2, "CI Node 24 runtime is not exact")
for digest in (
    "b294a556e639d64338823920e5866c21c02741742d2e1529ee1a225c1ec9252a",
    "013b59cfd2819703a6f4a14ab891fc46fc2a4e3f5bcd92de3fb4929b43e35b30",
    "f625d97cd707df4ff96254916fbc5ff014f09c09effe5a1e0ca8f6d41a8789d4",
    "d28c8a5bf0a808f0ed434a1dce8c54ae98f0371c0bd86ac58abc613f73e6643f",
):
    require(ci_workflow.count(digest) == 2, f"CI Node checksum is not pinned: {digest}")
require("6703a3a70a0c47cf0b37694030b54f1175a9dfeb17b3818b623ed58b9dbc2a77" in deploy_workflow, "deploy kustomize checksum missing")
require("sha256sum --check --strict" in deploy_workflow, "deploy downloads are not checksum verified")
require("working-directory: ${{ inputs." not in deploy_workflow, "unvalidated workflow input used as working-directory")
require("id: validate-overlay" in deploy_workflow, "deploy overlay path lacks a validation boundary")
require(
    "working-directory: ${{ steps.validate-overlay.outputs.overlay_path }}" in deploy_workflow,
    "deploy stamp does not consume the validated overlay path",
)
require(
    "OVERLAY_PATH: ${{ steps.validate-overlay.outputs.overlay_path }}" in deploy_workflow,
    "deploy commit does not consume the validated overlay path",
)
for buildx_marker in (
    "BUILDX_VERSION: v0.36.0",
    "BUILDKIT_IMAGE: moby/buildkit@sha256:2f5adac4ecd194d9f8c10b7b5d7bceb5186853db1b26e5abd3a657af0b7e26ec",
    "07823fdfcd82a41be90155a8b16876c1a780a6462de805a9f3f63b3119ccfb99",
    "70382de03915c07c488ae4ddc4f7e169ee978f953e754ecfce110ba017e0132b",
):
    require(buildx_marker in deploy_workflow, f"deploy Buildx toolchain is not pinned: {buildx_marker}")
require("docker/setup-buildx-action@" not in deploy_workflow, "deploy Buildx action download is not content-verified")
require(deploy_workflow.count("22|22.23.2) version=v22.23.2") == 1, "deploy Node 22 runtime is not exact")
require(deploy_workflow.count("24|24.19.0) version=v24.19.0") == 1, "deploy Node 24 runtime is not exact")
for digest in (
    "b294a556e639d64338823920e5866c21c02741742d2e1529ee1a225c1ec9252a",
    "013b59cfd2819703a6f4a14ab891fc46fc2a4e3f5bcd92de3fb4929b43e35b30",
    "f625d97cd707df4ff96254916fbc5ff014f09c09effe5a1e0ca8f6d41a8789d4",
    "d28c8a5bf0a808f0ed434a1dce8c54ae98f0371c0bd86ac58abc613f73e6643f",
):
    require(deploy_workflow.count(digest) == 1, f"deploy Node checksum is not pinned: {digest}")
require(deploy_workflow.startswith("name: Reusable Deploy Staging"), "unexpected deploy workflow")
require("permissions:\n  contents: read\n\njobs:" in deploy_workflow, "deploy workflow lacks read-only default permissions")
deploy_job = deploy_workflow.split("  deploy:", 1)[1].split("  notify:", 1)[0]
notify_job = deploy_workflow.split("  notify:", 1)[1]
require("permissions:\n      contents: write" in deploy_job, "deploy job lacks scoped write permission")
require("permissions:\n      contents: read" in notify_job, "notify job lacks read-only permission")
print("All third-party workflow dependencies are pinned to immutable commits")
