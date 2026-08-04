#!/usr/bin/env python3
"""Static fail-closed contract for the shared manifest promotion workflow."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
workflow = (ROOT / ".github/workflows/reusable-manifest-release.yml").read_text(encoding="utf-8")
self_release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)

required = [
    "promotion_mode:",
    "pull-requests: write",
    "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/github-script@ed597411d8f924073f98dfc5c65a23a2325f34cd",
    'if [ "$ORAS_VERSION" != "1.2.3" ]',
    "b4efc97a91f471f323f193ea4b4d63d8ff443ca3aab514151a30751330852827",
    "sha256sum --check --strict",
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
notify = workflow.split("  notify:", 1)[1]
require("contents: write" not in notify, "notify job must not write contents")
require("pull-requests: write" not in notify, "notify job must not write PRs")
require("promotion_mode: pull-request" in self_release, "self release must use PR promotion")
require("pull-requests: write" in self_release, "self release lacks PR permission")

print("GitOps manifest PR-promotion contract passed")
