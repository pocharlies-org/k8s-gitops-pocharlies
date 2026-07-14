#!/usr/bin/env python3
"""Static fail-closed contract for immutable image release evidence."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
workflow = (ROOT / ".github/workflows/reusable-release.yml").read_text(encoding="utf-8")

required = [
    "id-token: write",
    "aquasecurity/setup-trivy@81e514348e19b6112ce2a7e3ecbafe19c1e1f567",
    "sigstore/cosign-installer@6f9f17788090df1f26f669e9d70d6ae9567deba6",
    "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    "--scanners vuln,secret",
    "--severity HIGH,CRITICAL",
    "--ignore-unfixed",
    "--format spdx-json",
    "docker buildx imagetools inspect",
    'digest_ref="${base}@${digest}"',
    'cosign sign --yes "$digest_ref"',
    "cosign attest --yes --type spdxjson",
    "cosign verify \\",
    "cosign verify-attestation \\",
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
verify = loop.index("cosign verify \\")
evidence = loop.index("release-evidence.json")
assert scan < push < sign < attest < verify < evidence

assert '--tag "$version_ref"' in loop
assert '--tag "$sha_ref"' in loop
assert "--force" not in workflow
assert "COSIGN_PASSWORD" not in workflow

print("Immutable image release supply-chain contract passed")
