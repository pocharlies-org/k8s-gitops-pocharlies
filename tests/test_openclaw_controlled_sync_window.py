import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPLICATION = ROOT / "apps/openclaw-qwen36.yaml"

LEASE = "operations.pocharlies.org/state-writer-lease"
APPROVED_REVISION = "operations.pocharlies.org/approved-revision"
APPROVAL_ID = "operations.pocharlies.org/approval-id"
APPROVAL_SEQUENCE = "operations.pocharlies.org/approval-sequence"
APPROVED_PRUNE = "operations.pocharlies.org/approved-prune"
APPROVAL_KEYS = (
    APPROVED_REVISION,
    APPROVAL_ID,
    APPROVAL_SEQUENCE,
    APPROVED_PRUNE,
)


def _application_approval_annotations() -> dict[str, str]:
    manifest = APPLICATION.read_text(encoding="utf-8")
    annotations: dict[str, str] = {}
    for key in (LEASE, *APPROVAL_KEYS):
        match = re.search(
            rf"^\s+{re.escape(key)}:\s*(.*?)\s*$",
            manifest,
            flags=re.MULTILINE,
        )
        if match is None:
            continue
        value = match.group(1)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        annotations[key] = value
    return annotations


def _approval_state_is_valid(annotations: dict[str, str]) -> bool:
    lease = annotations.get(LEASE)
    present_approvals = {key for key in APPROVAL_KEYS if key in annotations}

    if lease == "inactive":
        return not present_approvals
    if lease != "active" or present_approvals != set(APPROVAL_KEYS):
        return False

    return all(
        (
            re.fullmatch(r"[0-9a-f]{40}", annotations[APPROVED_REVISION]),
            re.fullmatch(r"[a-z0-9][a-z0-9-]{7,63}", annotations[APPROVAL_ID]),
            re.fullmatch(r"[0-9]{14}", annotations[APPROVAL_SEQUENCE]),
            annotations[APPROVED_PRUNE] in {"true", "false"},
        )
    )


def _complete_active_bundle(*, prune: str = "false") -> dict[str, str]:
    return {
        LEASE: "active",
        APPROVED_REVISION: "a" * 40,
        APPROVAL_ID: "openclaw-prod-sync-a1b2c3d4",
        APPROVAL_SEQUENCE: "20260715052808",
        APPROVED_PRUNE: prune,
    }


class OpenClawControlledSyncWindowTest(unittest.TestCase):
    def test_automated_window_stays_closed_but_manual_recovery_is_allowed(self) -> None:
        project = (ROOT / "argocd/project-openclaw-controlled.yaml").read_text()

        self.assertIn('schedule: "0 5 * * *"', project)
        self.assertIn('duration: 22h', project)
        self.assertIn('manualSync: true', project)
        self.assertNotIn('manualSync: false', project)
        self.assertIn('after the state-writer lease rollout gate', project)

    def test_application_matches_one_complete_approval_state(self) -> None:
        annotations = _application_approval_annotations()

        self.assertTrue(_approval_state_is_valid(annotations))

    def test_inactive_state_rejects_stale_approval_fields(self) -> None:
        complete = _complete_active_bundle()

        self.assertTrue(_approval_state_is_valid({LEASE: "inactive"}))
        for key in APPROVAL_KEYS:
            with self.subTest(stale_key=key):
                self.assertFalse(
                    _approval_state_is_valid(
                        {LEASE: "inactive", key: complete[key]}
                    )
                )
        self.assertFalse(
            _approval_state_is_valid({**complete, LEASE: "inactive"})
        )

    def test_active_state_requires_the_complete_bundle(self) -> None:
        complete = _complete_active_bundle()

        self.assertTrue(_approval_state_is_valid(complete))
        self.assertTrue(
            _approval_state_is_valid(_complete_active_bundle(prune="true"))
        )
        for boundary_id in ("a1234567", "a" * 64):
            boundary = dict(complete)
            boundary[APPROVAL_ID] = boundary_id
            with self.subTest(boundary_id=boundary_id):
                self.assertTrue(_approval_state_is_valid(boundary))

        without_lease = dict(complete)
        without_lease.pop(LEASE)
        self.assertFalse(_approval_state_is_valid(without_lease))
        for missing_key in APPROVAL_KEYS:
            partial = dict(complete)
            partial.pop(missing_key)
            with self.subTest(missing_key=missing_key):
                self.assertFalse(_approval_state_is_valid(partial))

    def test_active_state_rejects_malformed_bundle_values(self) -> None:
        invalid_values = {
            APPROVED_REVISION: ("a" * 39, "a" * 41, "A" * 40, "g" * 40),
            APPROVAL_ID: (
                "short",
                "-openclaw-sync",
                "openclaw_sync",
                "Openclaw-sync",
                "a" * 65,
            ),
            APPROVAL_SEQUENCE: (
                "2026071505280",
                "202607150528080",
                "20260715t52808",
            ),
            APPROVED_PRUNE: ("False", "yes", "0", ""),
        }

        for key, values in invalid_values.items():
            for value in values:
                malformed = _complete_active_bundle()
                malformed[key] = value
                with self.subTest(key=key, value=value):
                    self.assertFalse(_approval_state_is_valid(malformed))

        self.assertFalse(_approval_state_is_valid({}))
        self.assertFalse(_approval_state_is_valid({LEASE: "pending"}))


if __name__ == "__main__":
    unittest.main()
