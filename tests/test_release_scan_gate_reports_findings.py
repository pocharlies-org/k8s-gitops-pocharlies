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
import tempfile
import unittest
from pathlib import Path

from _release_snippets import run_node, workflow_snippet

SUMMARY_MARKER = 'FAILED_REPORT="$trivy_report"'

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


def run_summary(report: dict) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        report_file = Path(tmp) / "report.json"
        report_file.write_text(json.dumps(report))
        result = run_node(workflow_snippet(SUMMARY_MARKER), {"FAILED_REPORT": str(report_file)})
    if result.returncode != 0:  # pragma: no cover - the snippet lost its happy path
        raise AssertionError(f"summary snippet failed: {result.stderr.strip()}")
    return result.stdout


class ScanGateReportsFindings(unittest.TestCase):
    def test_gate_failure_is_not_silent(self) -> None:
        out = run_summary(REPORT)
        self.assertIn("CVE-2026-111181", out)
        self.assertIn("body-parser 2.3.0", out)
        self.assertIn("fixed in 2.4.0, 1.20.9", out)
        self.assertIn("CVE-2023-54404", out)
        self.assertIn("github-pat", out)
        self.assertIn("app/config.js", out)

    def test_empty_report_says_so(self) -> None:
        self.assertIn("no findings", run_summary({"Results": []}))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
