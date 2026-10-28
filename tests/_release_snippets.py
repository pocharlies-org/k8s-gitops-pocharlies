"""Shared helpers for the release-workflow tests.

Extracts a node heredoc from `reusable-release.yml` verbatim (dedented to
column 0) and runs it with node, so each guard tests the snippet the workflow
actually ships. Single source: the duplicados check of the org rejects the
same extraction block copied per test file.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/reusable-release.yml"


def workflow_snippet(marker: str) -> str:
    """The first node heredoc introduced by `marker`, dedented to column 0."""
    pattern = re.compile(re.escape(marker) + r" node <<'NODE'\n(.*?)\n          NODE", re.S)
    match = pattern.search(WORKFLOW.read_text())
    if match is None:  # pragma: no cover - the workflow lost the snippet entirely
        raise AssertionError(f"could not find the node snippet after {marker!r} in the workflow")
    return "\n".join(
        line[10:] if line.startswith(" " * 10) else line for line in match.group(1).split("\n")
    )


def run_node(source: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - node, fixed args
        ["node", "-e", source],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
    )
