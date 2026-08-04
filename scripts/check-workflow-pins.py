#!/usr/bin/env python3
"""Reject mutable third-party actions in every shared workflow."""

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
IMMUTABLE_REF = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")

violations: list[str] = []

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
inline_mutant = yaml.safe_load(
    "jobs:\n  test:\n    steps:\n      - {uses: actions/checkout@v7}\n"
)
assert list(action_uses(inline_mutant)) == [
    ("jobs.test.steps[0].uses", "actions/checkout@v7")
]

workflows = sorted({*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")})
for workflow in workflows:
    text = workflow.read_text(encoding="utf-8")
    document = yaml.safe_load(text)
    for path, target in action_uses(document):
        if target.startswith("./"):
            continue
        if not IMMUTABLE_REF.fullmatch(target):
            violations.append(f"{workflow.relative_to(ROOT)}:{path}: {target}")

assert not violations, "mutable workflow dependencies:\n" + "\n".join(violations)

ci_workflow = (WORKFLOWS / "reusable-ci.yml").read_text(encoding="utf-8")
deploy_workflow = (WORKFLOWS / "reusable-deploy-stg.yml").read_text(encoding="utf-8")
for digest in (
    "6703a3a70a0c47cf0b37694030b54f1175a9dfeb17b3818b623ed58b9dbc2a77",
    "95f14e87aa28c09d5941f11bd024c1d02fdc0303ccaa23f61cef67bc92619d73",
):
    assert digest in ci_workflow, f"missing CI tool checksum: {digest}"
assert "sha256sum --check --strict" in ci_workflow
assert "repository: ${{ job.workflow_repository }}" in ci_workflow
assert "ref: ${{ job.workflow_sha }}" in ci_workflow
checker_checkout = ci_workflow.split("      - name: Check out the contract checker", 1)[1].split(
    "      - name: Enforce the contract rules", 1
)[0]
assert "persist-credentials: false" in checker_checkout
assert "6703a3a70a0c47cf0b37694030b54f1175a9dfeb17b3818b623ed58b9dbc2a77" in deploy_workflow
assert "sha256sum --check --strict" in deploy_workflow
assert deploy_workflow.startswith("name: Reusable Deploy Staging")
assert "permissions:\n  contents: read\n\njobs:" in deploy_workflow
deploy_job = deploy_workflow.split("  deploy:", 1)[1].split("  notify:", 1)[0]
notify_job = deploy_workflow.split("  notify:", 1)[1]
assert "permissions:\n      contents: write" in deploy_job
assert "permissions:\n      contents: read" in notify_job
print("All third-party workflow dependencies are pinned to immutable commits")
