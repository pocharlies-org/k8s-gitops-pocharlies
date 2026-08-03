#!/usr/bin/env python3
"""Static fail-closed contract for the shared manifest promotion workflow."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
workflow = (ROOT / ".github/workflows/reusable-manifest-release.yml").read_text(encoding="utf-8")
self_release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

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
    assert marker in workflow, f"missing manifest promotion guard: {marker}"

pr_section = workflow.split("Prepare promotion commit on latest Argo branch", 1)[1]
assert "--force" not in pr_section
assert "gh pr" not in pr_section
assert "github.rest.pulls.merge" not in workflow
assert workflow.count("pull-requests: write") == 1
notify = workflow.split("  notify:", 1)[1]
assert "contents: write" not in notify
assert "pull-requests: write" not in notify
assert "promotion_mode: pull-request" in self_release
assert "pull-requests: write" in self_release

print("GitOps manifest PR-promotion contract passed")
