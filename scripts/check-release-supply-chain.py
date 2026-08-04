#!/usr/bin/env python3
"""Static fail-closed contract for immutable image release evidence."""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
workflow = (ROOT / ".github/workflows/reusable-release.yml").read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)

required = [
    "id-token: write",
    "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
    "version=v24.19.0",
    "version=v22.23.2",
    "b294a556e639d64338823920e5866c21c02741742d2e1529ee1a225c1ec9252a",
    "013b59cfd2819703a6f4a14ab891fc46fc2a4e3f5bcd92de3fb4929b43e35b30",
    "f625d97cd707df4ff96254916fbc5ff014f09c09effe5a1e0ca8f6d41a8789d4",
    "d28c8a5bf0a808f0ed434a1dce8c54ae98f0371c0bd86ac58abc613f73e6643f",
    "docker/login-action@dbcb813823bdd20940b903addbd779551569679f",
    "actions/github-script@ed597411d8f924073f98dfc5c65a23a2325f34cd",
    "TRIVY_VERSION: v0.70.0",
    "8b4376d5d6befe5c24d503f10ff136d9e0c49f9127a4279fd110b727929a5aa9",
    "2f6bb988b553a1bbac6bdd1ce890f5e412439564e17522b88a4541b4f364fc8d",
    "COSIGN_VERSION: v3.0.6",
    "https://github.com/sigstore/cosign/releases/download/",
    "c956e5dfcac53d52bcf058360d579472f0c1d2d9b69f55209e256fe7783f4c74",
    "bedac92e8c3729864e13d4a17048007cfafa79d5deca993a43a90ffe018ef2b8",
    "sha256sum --check --strict",
    "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    "--scanners vuln,secret",
    "--severity HIGH,CRITICAL",
    "--ignore-unfixed",
    "--format spdx-json",
    "docker buildx imagetools inspect",
    "/api/v2.0/projects/${project_encoded}/repositories/${repository_encoded}/artifacts/${digest_encoded}/tags",
    "Atomically created immutable release tag",
    "Release tag already exists; verifying digest",
    'for promoted_ref in "$sha_ref" "$version_ref"; do',
    "BUILDX_VERSION: v0.36.0",
    "BUILDKIT_IMAGE: moby/buildkit@sha256:2f5adac4ecd194d9f8c10b7b5d7bceb5186853db1b26e5abd3a657af0b7e26ec",
    "07823fdfcd82a41be90155a8b16876c1a780a6462de805a9f3f63b3119ccfb99",
    "70382de03915c07c488ae4ddc4f7e169ee978f953e754ecfce110ba017e0132b",
    'digest_ref="${base}@${digest}"',
    'cosign sign --yes "$digest_ref"',
    "cosign attest --yes --type spdxjson",
    "cosign attest --yes --type slsaprovenance1",
    "cosign verify \\",
    "cosign verify-attestation \\",
    'candidate_ref="${base}:candidate-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"',
    'push_image "$candidate_ref"',
    'done < "$evidence_dir/promotions.tsv"',
    'buildType: "https://github.com/Attestations/GitHubActionsWorkflow@v1"',
    'digest: { sha1: process.env.GITHUB_SHA }',
    'id: `https://github.com/${process.env.JOB_WORKFLOW_REF}`',
    "JOB_WORKFLOW_REF: ${{ job.workflow_ref }}",
    "JOB_WORKFLOW_SHA: ${{ job.workflow_sha }}",
    "Reusable release workflow must be called by immutable commit SHA",
    'certificate_identity="https://github.com/${JOB_WORKFLOW_REF}"',
    'attestations: ["https://spdx.dev/Document", "https://slsa.dev/provenance/v1"]',
    "pocharlies-org/k8s-gitops-pocharlies/\\.github/workflows/reusable-release\\.yml@[0-9a-f]{40}",
    "https://token.actions.githubusercontent.com",
    '--certificate-github-workflow-repository "$GITHUB_REPOSITORY"',
    '--certificate-github-workflow-sha "$GITHUB_SHA"',
    "release-evidence.json",
    "retention-days: 90",
    "Legacy .trivyignore is forbidden",
    "trivy-policy.trivyignore.yaml",
    "--ignorefile \"$policy_file\"",
    "--show-suppressed",
    "ModifiedFindings",
    "trivyPolicySha256",
    "if: ${{ always() }}",
]
for marker in required:
    require(marker in workflow, f"missing release supply-chain guard: {marker}")

loop = workflow.split("while IFS=$'\\t' read -r name context dockerfile; do", 1)[1]
scan = loop.index("trivy image")
candidate_push = loop.index('push_image "$candidate_ref"')
final_push = loop.index('status="$(curl --silent --show-error')
sign = loop.index('cosign sign --yes "$digest_ref"')
attest = loop.index("cosign attest --yes --type spdxjson")
provenance = loop.index("cosign attest --yes --type slsaprovenance1")
verify = loop.index("cosign verify \\")
evidence = loop.index("release-evidence.json")
require(scan < candidate_push < sign < attest < provenance < verify < final_push < evidence, "release gates are out of order")

slsa_verify = "cosign verify-attestation \\\n              --type slsaprovenance1"
require(slsa_verify in loop, "SLSA provenance must be verified before evidence publication")
require(provenance < loop.index(slsa_verify) < final_push < evidence, "SLSA verification occurs too late")

build_block = loop.split("# Fail before publication", 1)[0]
require('--tag "$candidate_ref"' in build_block, "build does not target candidate tag")
require("docker buildx build \\" in build_block, "release does not use the pinned Buildx builder")
require("--load \\" in build_block, "candidate image is not loaded for local scanning")
require("--network=host" not in workflow, "host networking is forbidden for release builds")
require('--tag "$version_ref"' not in build_block, "version tag is built before verification")
require('--tag "$sha_ref"' not in build_block, "SHA tag is built before verification")
require('push_image "$version_ref"' not in workflow, "final version tag must be promoted from verified digest")
require('push_image "$sha_ref"' not in workflow, "final SHA tag must be promoted from verified digest")
require("docker/setup-buildx-action@" not in workflow, "Buildx action download is not content-verified")
require("aquasecurity/setup-trivy@" not in workflow, "Trivy action download is not content-verified")
require("docker buildx imagetools create" not in workflow, "release tags must use Harbor atomic CreateTag")
require("case \"$status\" in" in workflow and "201)" in workflow and "409)" in workflow, "Harbor CreateTag status handling is incomplete")
require("--netrc-file \"$harbor_netrc\"" in workflow, "Harbor CreateTag is not authenticated")
require("--force" not in workflow, "forced attestation replacement is forbidden")
require("COSIGN_PASSWORD" not in workflow, "key-based Cosign material is forbidden")
require(workflow.count("id-token: write") == 1, "OIDC permission must be isolated to release job")
notify = workflow.split("  notify:", 1)[1]
require("id-token: write" not in notify, "notify job must not receive OIDC permission")
require("${GITHUB_REPOSITORY}/.github/workflows/[^@]+" not in workflow, "mutable certificate identity accepted")

require("--certificate-identity-regexp" not in workflow, "certificate regex identity is forbidden")
require(workflow.count('--certificate-identity "$certificate_identity"') == 3, "all Cosign evidence must verify exact identity")
require(workflow.count('--certificate-github-workflow-repository "$GITHUB_REPOSITORY"') == 3, "all Cosign evidence must bind caller repository")
require(workflow.count('--certificate-github-workflow-sha "$GITHUB_SHA"') == 3, "all Cosign evidence must bind caller revision")
require("refs/(heads|tags)" not in workflow, "mutable certificate reference accepted")

expected_workflow_digest = "ad619faebb3631837ec7efe8d674a6258243ee2a92ed7e4c82828f4c287a94cf"
workflow_digest = hashlib.sha256(workflow.encode()).hexdigest()
require(
    workflow_digest == expected_workflow_digest,
    f"release workflow changed without review: {workflow_digest}",
)
require(
    hashlib.sha256((workflow + "\nenv:\n  MALICIOUS: true\n").encode()).hexdigest()
    != expected_workflow_digest,
    "release job mutation self-test failed",
)
require(
    hashlib.sha256(workflow.replace("harbor.lan.e-dani.com", "evil.invalid").encode()).hexdigest()
    != expected_workflow_digest,
    "workflow-call input mutation self-test failed",
)

print("Immutable image release supply-chain contract passed")
