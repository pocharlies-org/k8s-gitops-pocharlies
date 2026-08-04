#!/usr/bin/env python3
"""Static fail-closed contract for the shared manifest promotion workflow."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
legacy = (ROOT / ".github/workflows/reusable-manifest-release.yml").read_text(encoding="utf-8")
workflow = (ROOT / ".github/workflows/reusable-manifest-pr-release.yml").read_text(encoding="utf-8")
self_release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)

required = [
    "pull-requests: write",
    "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/github-script@ed597411d8f924073f98dfc5c65a23a2325f34cd",
    'if [ "$ORAS_VERSION" != "1.2.3" ]',
    "b4efc97a91f471f323f193ea4b4d63d8ff443ca3aab514151a30751330852827",
    "sha256sum --check --strict",
    'if [ "$REGISTRY" != "harbor.lan.e-dani.com" ]',
    'CANDIDATE_REF="${REGISTRY}/${REGISTRY_PROJECT}/${ARTIFACT_NAME}:candidate-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"',
    'ARTIFACT_DIGEST="$(oras resolve "$CANDIDATE_REF")"',
    "Validate immutable reusable workflow identity",
    "Reusable manifest workflow must be called by immutable commit SHA",
    "JOB_WORKFLOW_REF: ${{ job.workflow_ref }}",
    "JOB_WORKFLOW_SHA: ${{ job.workflow_sha }}",
    'source_tree_sha="$(git rev-parse "${PATCHED_TREE_SHA}:${SOURCE_PATH}")"',
    'source_tree_sha="$(git rev-parse "${PATCHED_TREE_SHA}^{tree}")"',
    "git archive \\",
    '"$source_tree_sha"',
    '--mtime="@${source_epoch}"',
    "source_path must not contain tracked symlinks",
    "source_path must not contain gitlinks or submodules",
    "export-ignore",
    "export-subst",
    'gzip -n -9 "$bundle_tar"',
    '"manifest-bundle.tar.gz:application/vnd.oci.image.layer.v1.tar+gzip"',
    'for tag in "$SHA_TAG" "$VERSION"; do',
    "/api/v2.0/projects/${project_encoded}/repositories/${repository_encoded}/artifacts/${digest_encoded}/tags",
    "Atomically created immutable manifest tag",
    "Manifest tag already exists; verifying digest",
    "verify_harbor_tag_on_digest()",
    "?page=${page}&page_size=100",
    'any(.[]; .name == $expected_tag)',
    'case "$http_code" in',
    "201)",
    "409)",
    'resolved="$(oras resolve "$tag_ref")"',
    'oras manifest fetch "$tag_ref"',
    'Candidate manifest is not bound to the source, patched tree, and image digest set',
    'Immutable manifest tag linkage mismatch',
    "image_promotions:",
    "image_targets:",
    "image target names must exactly match released image names",
    "rendered image linkage mismatch",
    "manifest_only is restricted to the central source-bound self-release",
    "image releases require non-empty promotions and exact targets",
    "Verify deployment registry digest aliases",
    'oras resolve "${repository}@${digest}"',
    "rho.skirmshop.es/patched-tree",
    "rho.skirmshop.es/image-digest-set-sha256",
    "6703a3a70a0c47cf0b37694030b54f1175a9dfeb17b3818b623ed58b9dbc2a77",
    "fc307327959aa38ed8f9f7e66d45492bb022a66c3e5da6063958254b9767d179",
    'git fetch origin "$DEPLOY_BRANCH"',
    'git checkout -B "$PROMOTION_BRANCH" "origin/$DEPLOY_BRANCH"',
    'git read-tree --reset -u "$SOURCE_SHA"',
    'git read-tree --reset -u "$PATCHED_TREE_SHA"',
    "github.rest.pulls.create",
    "github.rest.pulls.list",
    "No workflow will auto-merge this PR.",
]
for marker in required:
    require(marker in workflow, f"missing manifest promotion guard: {marker}")

pr_section = workflow.split("Prepare promotion commit on latest Argo branch", 1)[1]
require("--force" not in pr_section, "force push is forbidden in manifest promotion")
require("gh pr" not in pr_section, "manifest promotion must use scoped GitHub API")
require("github.rest.pulls.merge" not in workflow, "manifest promotion must not auto-merge")
require(workflow.count("pull-requests: write") == 1, "PR write permission must be isolated")
require("oras copy" not in workflow, "manifest release must use atomic Harbor CreateTag")
require(workflow.count("?page=${page}&page_size=100") == 1, "manifest Harbor nested tag lookup must be paginated exactly once")
require(workflow.count('any(.[]; .name == $expected_tag)') == 1, "manifest reconciliation must match the exact tag name")
require(workflow.count('verify_harbor_tag_on_digest "$tag"') == 1, "manifest reconciliation function must be invoked exactly once")
manifest_case = workflow.index('case "$http_code" in')
manifest_reconcile = workflow.index('verify_harbor_tag_on_digest "$tag"')
manifest_resolve = workflow.index('resolved="$(oras resolve "$tag_ref")"')
require(manifest_case < manifest_reconcile < manifest_resolve, "manifest reconciliation is out of promotion order")
require(workflow.index('for tag in "$SHA_TAG" "$VERSION"; do') < workflow.index('ARTIFACT_REF=$REF'), "immutable manifest tags are published too late")
stamp = workflow.index("Stamp and verify exact release image digests")
publish = workflow.index("Publish Argo CD OCI manifest bundle")
reset_source = workflow.index('git read-tree --reset -u "$SOURCE_SHA"')
reset_patched = workflow.index('git read-tree --reset -u "$PATCHED_TREE_SHA"')
require(stamp < publish < reset_source < reset_patched, "manifest promotion does not preserve the stamped tree")
require(workflow.count('git read-tree --reset -u "$PATCHED_TREE_SHA"') == 1, "patched tree must be promoted exactly once")
notify = workflow.split("  notify:", 1)[1]
require("contents: write" not in notify, "notify job must not write contents")
require("pull-requests: write" not in notify, "notify job must not write PRs")
require("pull-requests: write" in self_release, "self release lacks PR permission")
require("./.github/workflows/reusable-manifest-pr-release.yml" in self_release, "self release must use PR workflow")
require("manifest_only: true" in self_release, "self release must explicitly declare manifest-only mode")

legacy_required = [
    "Reusable Manifest OCI Legacy Release",
    "Promote deploy branch directly (legacy compatibility)",
    'git push origin "HEAD:refs/heads/${DEPLOY_BRANCH}" --force-with-lease',
    'for tag in "$SHA_TAG" "$VERSION"; do',
    "Atomically created immutable manifest tag",
    "verify_harbor_tag_on_digest()",
    "?page=${page}&page_size=100",
    'any(.[]; .name == $expected_tag)',
]
for marker in legacy_required:
    require(marker in legacy, f"missing legacy manifest compatibility guard: {marker}")
require("pull-requests: write" not in legacy, "legacy workflow must not request PR write permission")
require("github.rest.pulls." not in legacy, "legacy workflow must not contain PR mutation code")
require("promotion_mode:" not in legacy and "promotion_mode:" not in workflow, "split workflows must not retain conditional permission mode")
require("oras copy" not in legacy, "legacy manifest release must use atomic Harbor CreateTag")
require(legacy.count("?page=${page}&page_size=100") == 1, "legacy Harbor nested tag lookup must be paginated exactly once")
require(legacy.count('any(.[]; .name == $expected_tag)') == 1, "legacy reconciliation must match the exact tag name")
require(legacy.count('verify_harbor_tag_on_digest "$tag"') == 1, "legacy reconciliation function must be invoked exactly once")
legacy_case = legacy.index('case "$http_code" in')
legacy_reconcile = legacy.index('verify_harbor_tag_on_digest "$tag"')
legacy_resolve = legacy.index('resolved="$(oras resolve "$tag_ref")"')
require(legacy_case < legacy_reconcile < legacy_resolve, "legacy reconciliation is out of promotion order")

print("GitOps manifest PR-promotion contract passed")
