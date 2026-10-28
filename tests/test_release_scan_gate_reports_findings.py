"""A failed Trivy gate must print its blocking findings, not exit silently.

Regression guard for SC-2856: the gate writes its report to a file
(`--format json --output`), so when it exits 1 the step log ends with the
Trivy notices and "Process completed with exit code 1" — no finding, no
package, no message. A release of k8s-socialmedia-pocharlies died that way
on three fixable HIGHs (body-parser, multer, zod) and cost a full IT
investigation to diagnose.

This runs the summary snippet extracted verbatim from the workflow against a
report shaped like Trivy's (the failing mcp-server report of run
40431186404, reduced) and requires each blocking finding to be named.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/reusable-release.yml"
SUMMARY = re.compile(
    r'FAILED_REPORT="\$trivy_report" node <<\'NODE\'\n(.*?)\n          NODE',
    re.S,
)

REPORT = {
    "Results": [
        {
            "Target": "Node.js",
            "Vulnerabilities": [
                {
                    "VulnerabilityID": "CVE-2026-111181",
                    "PkgName": "body-parser",
                    "InstalledVersion": "2.3.0",
                    "FixedVersion": "2.4.0, 1.20.9",
                    "Severity": "HIGH",
                },
                {
                    "VulnerabilityID": "CVE-2023-54404",
                    "PkgName": "zod",
                    "InstalledVersion": "3.25.76",
                    "FixedVersion": "4.6.6",
                    "Severity": "HIGH",
                },
            ],
            "Secrets": [
                {"RuleID": "github-pat", "FilePath": "app/config.js"},
            ],
        },
    ],
}


def summary_source() -> str:
    match = SUMMARY.search(WORKFLOW.read_text())
    if match is None:  # pragma: no cover - the workflow lost the summary entirely
        raise AssertionError("could not find the failed-gate summary snippet in the workflow")
    return "\n".join(
        line[10:] if line.startswith(" " * 10) else line for line in match.group(1).split("\n")
    )


class ScanGateReportsFindings(unittest.TestCase):
    def test_gate_failure_is_not_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = os.path.join(tmp, "report.json")
            with open(report, "w") as handle:
                json.dump(REPORT, handle)
            env = {**os.environ, "FAILED_REPORT": report}
            result = subprocess.run(  # noqa: S603 - node, fixed args
                ["node", "-e", summary_source()],
                env=env,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout
        self.assertIn("CVE-2026-111181", out)
        self.assertIn("body-parser 2.3.0", out)
        self.assertIn("fixed in 2.4.0, 1.20.9", out)
        self.assertIn("CVE-2023-54404", out)
        self.assertIn("github-pat", out)
        self.assertIn("app/config.js", out)

    def test_empty_report_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = os.path.join(tmp, "report.json")
            with open(report, "w") as handle:
                json.dump({"Results": []}, handle)
            env = {**os.environ, "FAILED_REPORT": report}
            result = subprocess.run(  # noqa: S603 - node, fixed args
                ["node", "-e", summary_source()],
                env=env,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no findings", result.stdout)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
