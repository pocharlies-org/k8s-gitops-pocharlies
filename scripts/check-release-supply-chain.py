#!/usr/bin/env python3
"""Static fail-closed contract for immutable image release evidence."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
workflow = (ROOT / ".github/workflows/reusable-release.yml").read_text(encoding="utf-8")

required = [
    "id-token: write",
    "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/setup-node@249970729cb0ef3589644e2896645e5dc5ba9c38",
    "docker/login-action@dbcb813823bdd20940b903addbd779551569679f",
    "actions/github-script@ed597411d8f924073f98dfc5c65a23a2325f34cd",
    "aquasecurity/setup-trivy@81e514348e19b6112ce2a7e3ecbafe19c1e1f567",
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
    'digest_ref="${base}@${digest}"',
    'cosign sign --yes "$digest_ref"',
    "cosign attest --yes --type spdxjson",
    "cosign attest --yes --type slsaprovenance1",
    "cosign verify \\",
    "cosign verify-attestation \\",
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
    "release-evidence.json",
    "retention-days: 90",
]
for marker in required:
    assert marker in workflow, f"missing release supply-chain guard: {marker}"

loop = workflow.split("while IFS=$'\\t' read -r name context dockerfile; do", 1)[1]
scan = loop.index("trivy image")
push = loop.index('push_image "$version_ref"')
sign = loop.index('cosign sign --yes "$digest_ref"')
attest = loop.index("cosign attest --yes --type spdxjson")
provenance = loop.index("cosign attest --yes --type slsaprovenance1")
verify = loop.index("cosign verify \\")
evidence = loop.index("release-evidence.json")
assert scan < push < sign < attest < provenance < verify < evidence

slsa_verify = "cosign verify-attestation \\\n              --type slsaprovenance1"
assert slsa_verify in loop, "SLSA provenance must be verified before evidence publication"
assert provenance < loop.index(slsa_verify) < evidence

assert '--tag "$version_ref"' in loop
assert '--tag "$sha_ref"' in loop
assert "--force" not in workflow
assert "COSIGN_PASSWORD" not in workflow
assert workflow.count("id-token: write") == 1
notify = workflow.split("  notify:", 1)[1]
assert "id-token: write" not in notify
assert "${GITHUB_REPOSITORY}/.github/workflows/[^@]+" not in workflow

assert "--certificate-identity-regexp" not in workflow
assert workflow.count('--certificate-identity "$certificate_identity"') == 3
assert "refs/(heads|tags)" not in workflow

print("Immutable image release supply-chain contract passed")
