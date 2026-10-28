"""The emitted Trivy policy must be parseable by the Trivy the workflow pins.

Regression guard for a contradiction that broke every release in every repo
carrying a Trivy exception: the workflow's own validator REQUIRES `expired_at`
as a bare calendar date, then hands the file to Trivy, whose Go decoder maps
that field onto time.Time with an RFC3339 layout and dies on a quoted date
("cannot parse \"\" as \"T\""). Authors keep writing bare dates; the emitted
file is normalised to midnight UTC.

This runs the node snippet extracted verbatim from the workflow, so it fails if
someone edits the emitter back into an unparseable shape.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from _release_snippets import run_node, workflow_snippet

EMITTER_MARKER = (
    'POLICY_SOURCE="$policy_source" '
    'POLICY_OUTPUT="$evidence_dir/trivy-policy.trivyignore.yaml"'
)


def run_emitter(policy: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "in.trivyignore.yaml"
        output = Path(tmp) / "out.trivyignore.yaml"
        source.write_text(json.dumps(policy))
        result = run_node(
            workflow_snippet(EMITTER_MARKER),
            {"POLICY_SOURCE": str(source), "POLICY_OUTPUT": str(output)},
        )
        if result.returncode != 0:
            raise AssertionError(f"emitter rejected the policy: {result.stderr.strip()}")
        return json.loads(output.read_text())


class TrivyPolicyEmitterTest(unittest.TestCase):
    def test_bare_dates_are_emitted_as_rfc3339(self) -> None:
        emitted = run_emitter(
            {
                "vulnerabilities": [
                    {"id": "CVE-2026-69152", "expired_at": "2126-09-14", "statement": "probe"}
                ]
            }
        )
        self.assertEqual(emitted["vulnerabilities"][0]["expired_at"], "2126-09-14T00:00:00Z")

    def test_every_section_is_normalised(self) -> None:
        emitted = run_emitter(
            {
                "vulnerabilities": [{"id": "CVE-1", "expired_at": "2126-01-02", "statement": "a"}],
                "secrets": [{"id": "SEC-1", "expired_at": "2126-01-03", "statement": "b"}],
                "misconfigurations": [{"id": "MIS-1", "expired_at": "2126-01-04", "statement": "c"}],
                "licenses": [{"id": "LIC-1", "expired_at": "2126-01-05", "statement": "d"}],
            }
        )
        for section, entries in emitted.items():
            for entry in entries:
                self.assertTrue(
                    entry["expired_at"].endswith("T00:00:00Z"),
                    f"{section} left an un-normalised expired_at: {entry['expired_at']}",
                )

    def test_the_author_facing_contract_is_still_a_bare_date(self) -> None:
        # An author who writes RFC3339 by hand must be rejected, so the emitter
        # stays the single place that knows about the wire format.
        with self.assertRaises(AssertionError):
            run_emitter(
                {
                    "vulnerabilities": [
                        {"id": "CVE-2", "expired_at": "2126-01-02T00:00:00Z", "statement": "a"}
                    ]
                }
            )

    def test_statement_and_id_survive_normalisation(self) -> None:
        emitted = run_emitter(
            {
                "vulnerabilities": [
                    {
                        "id": "CVE-3",
                        "expired_at": "2126-01-02",
                        "statement": "why it cannot be fixed",
                        "purls": ["pkg:npm/brace-expansion@5.0.8"],
                    }
                ]
            }
        )
        entry = emitted["vulnerabilities"][0]
        self.assertEqual(entry["id"], "CVE-3")
        self.assertEqual(entry["statement"], "why it cannot be fixed")
        self.assertEqual(entry["purls"], ["pkg:npm/brace-expansion@5.0.8"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
