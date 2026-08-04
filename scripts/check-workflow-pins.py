#!/usr/bin/env python3
"""Reject mutable third-party actions in every shared workflow."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
USE = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)", re.MULTILINE)
IMMUTABLE_REF = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")

violations: list[str] = []
for workflow in sorted(WORKFLOWS.glob("*.yml")):
    text = workflow.read_text(encoding="utf-8")
    for match in USE.finditer(text):
        target = match.group(1)
        if target.startswith("./"):
            continue
        if not IMMUTABLE_REF.fullmatch(target):
            line = text.count("\n", 0, match.start()) + 1
            violations.append(f"{workflow.relative_to(ROOT)}:{line}: {target}")

assert not violations, "mutable workflow dependencies:\n" + "\n".join(violations)
print("All third-party workflow dependencies are pinned to immutable commits")
