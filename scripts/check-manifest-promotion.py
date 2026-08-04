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
    "--sort=name",
    '--mtime="@${source_epoch}"',
    "--numeric-owner",
    'gzip -n -9 "$bundle_tar"',
    '"manifest-bundle.tar.gz:application/vnd.oci.image.layer.v1.tar+gzip"',
    'for tag in "$SHA_TAG" "$VERSION"; do',
    "/api/v2.0/projects/${project_encoded}/repositories/${repository_encoded}/artifacts/${digest_encoded}/tags",
    "Atomically created immutable manifest tag",
    "Manifest tag already exists; verifying digest",
    'case "$http_code" in',
    "201)",
    "409)",
    'resolved="$(oras resolve "$tag_ref")"',
    'oras manifest fetch "$tag_ref"',
    'Candidate manifest is not bound to the full source revision',
    'Immutable manifest tag revision mismatch',
    'git fetch origin "$DEPLOY_BRANCH"',
    'git checkout -B "$PROMOTION_BRANCH" "origin/$DEPLOY_BRANCH"',
    'git read-tree --reset -u "$SOURCE_SHA"',
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
require(workflow.index('for tag in "$SHA_TAG" "$VERSION"; do') < workflow.index('ARTIFACT_REF=$REF'), "immutable manifest tags are published too late")
notify = workflow.split("  notify:", 1)[1]
require("contents: write" not in notify, "notify job must not write contents")
require("pull-requests: write" not in notify, "notify job must not write PRs")
require("pull-requests: write" in self_release, "self release lacks PR permission")
require("./.github/workflows/reusable-manifest-pr-release.yml" in self_release, "self release must use PR workflow")

legacy_required = [
    "Reusable Manifest OCI Legacy Release",
    "Promote deploy branch directly (legacy compatibility)",
    'git push origin "HEAD:refs/heads/${DEPLOY_BRANCH}" --force-with-lease',
    'for tag in "$SHA_TAG" "$VERSION"; do',
    "Atomically created immutable manifest tag",
]
for marker in legacy_required:
    require(marker in legacy, f"missing legacy manifest compatibility guard: {marker}")
require("pull-requests: write" not in legacy, "legacy workflow must not request PR write permission")
require("github.rest.pulls." not in legacy, "legacy workflow must not contain PR mutation code")
require("promotion_mode:" not in legacy and "promotion_mode:" not in workflow, "split workflows must not retain conditional permission mode")
require("oras copy" not in legacy, "legacy manifest release must use atomic Harbor CreateTag")

print("GitOps manifest PR-promotion contract passed")
