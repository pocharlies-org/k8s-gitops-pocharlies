#!/usr/bin/env python3
"""Negative tests for check-contracts.py — prove every rule can actually fail.

The checker is what stands between an AI session and a silently broken contract,
and with no pull requests there is no second reader. So each rule gets a test
that degrades a real git repo on purpose and demands rejection, plus a positive
case so the checker is not merely always-red. Modelled on
k8s-agentgateway-pocharlies/scripts/test-check-mcp-coverage.py.

Run: python3 -m pytest scripts/test-check-contracts.py -q
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SPEC = importlib.util.spec_from_file_location(
    "check_contracts", Path(__file__).resolve().parent / "check-contracts.py"
)
cc = importlib.util.module_from_spec(SPEC)
sys.modules["check_contracts"] = cc
SPEC.loader.exec_module(cc)


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real git repo with one publisher file and a matching registry."""
    _run_git(tmp_path, "init", "-q", "-b", "main")
    _run_git(tmp_path, "config", "user.email", "t@example.com")
    _run_git(tmp_path, "config", "user.name", "T")

    src = tmp_path / "app" / "services"
    src.mkdir(parents=True)
    (src / "publisher.ts").write_text(
        "// CONTRACT: messaging.draft_email (consumer: adapter-messaging-agent)\n"
        'const ACTION = "draft_email";\n'
        'export const KEY = `messaging.${tenant}.draft_email`;\n',
        encoding="utf-8",
    )
    write_registry(
        tmp_path,
        [
            {
                "id": "messaging.draft_email",
                "kind": "routing-key",
                "value": "messaging.{tenant}.draft_email",
                "role": "publisher",
                "files": ["app/services/publisher.ts"],
                "status": "active",
            }
        ],
    )
    _run_git(tmp_path, "add", "-A")
    _run_git(tmp_path, "commit", "-qm", "initial")
    return tmp_path


def write_registry(repo: Path, contracts: list[dict], **extra) -> None:
    (repo / "CONTRACTS.yaml").write_text(
        yaml.safe_dump({"version": 1, "contracts": contracts, **extra}, sort_keys=False),
        encoding="utf-8",
    )


def rename_in_code(repo: Path, old: str, new: str) -> None:
    """Rename in the code lines only, leaving the `# CONTRACT:` marker intact.

    Renaming the marker too would trip marker-unregistered and mask the check
    each test is actually about.
    """
    target = repo / "app" / "services" / "publisher.ts"
    lines = [
        line if "CONTRACT:" in line else line.replace(old, new)
        for line in target.read_text(encoding="utf-8").splitlines(keepends=True)
    ]
    target.write_text("".join(lines), encoding="utf-8")


def check(repo: Path, rev_range: str | None = None) -> int:
    argv = ["check-contracts.py", "--repo", str(repo)]
    if rev_range:
        argv += ["--range", rev_range]
    old = sys.argv
    sys.argv = argv
    try:
        return cc.main()
    finally:
        sys.argv = old


# ── the checker must be green on a healthy repo ─────────────────────────────


def test_passes_on_a_healthy_repo(repo, capsys):
    assert check(repo) == 0
    assert "OK" in capsys.readouterr().out


def test_no_registry_means_nothing_to_enforce(tmp_path):
    """Repos with no contract surface must not be forced to declare one."""
    assert check(tmp_path) == 0


# ── rule: an active value must still exist where it claims to ───────────────


def test_rejects_a_renamed_routing_key(repo, capsys):
    """The 2026-07-28 incident, reproduced: consumer renamed, registry stale."""
    rename_in_code(repo, "draft_email", "draft_email_v2")
    assert check(repo) == 1
    assert "value-absent" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("template", "text", "should_match"),
    [
        ("messaging.{tenant}.draft_email", "`messaging.${t}.draft_email`", True),
        # The filler may itself contain dots: labels writes ${config.tenant}.
        ("messaging.{tenant}.send", "`messaging.${config.tenant}.send`", True),
        ("messaging.{tenant}.draft_email", "messaging.skirmshop.draft_email", True),
        # The trap: an APPENDING rename. Plain substring matching says "still
        # there" and the break ships silently.
        ("messaging.{tenant}.draft_email", "messaging.skirmshop.draft_email_v2", False),
        ("messaging.{tenant}.draft_email", "messaging.skirmshop.draft_emails", False),
        ("email.{tenant}.draft", "email.skirmshop.draft_email", False),
        ("document.intake.requested.v1", "document.intake.requested.v1", True),
        ("document.intake.requested.v1", "document.intake.requested.v2", False),
    ],
)
def test_value_matching_is_token_exact(template, text, should_match):
    assert bool(cc._value_pattern(template).search(text)) is should_match


def test_anchor_checks_a_composed_key(repo, capsys):
    """Keys built at runtime have no literal to grep; the anchor stands in.

    shopify-sii-app calls `createEmailDraft(...)` and the routing key is
    assembled inside the npm package — nothing in the repo contains the key. The
    anchor makes such a publisher checkable at all.
    """
    (repo / "app" / "services" / "composed.ts").write_text(
        "// CONTRACT: messaging.composed\nawait createEmailDraft({ to });\n", encoding="utf-8"
    )
    write_registry(
        repo,
        [
            {
                "id": "messaging.draft_email",
                "value": "messaging.{tenant}.draft_email",
                "files": ["app/services/publisher.ts"],
                "status": "active",
            },
            {
                "id": "messaging.composed",
                "value": "messaging.{tenant}.draft_email",
                "anchor": "createEmailDraft",
                "files": ["app/services/composed.ts"],
                "status": "active",
            },
        ],
    )
    assert check(repo) == 0


def test_rejects_a_composed_key_whose_anchor_vanished(repo, capsys):
    (repo / "app" / "services" / "composed.ts").write_text(
        "// CONTRACT: messaging.composed\nawait sendSomethingElse({ to });\n", encoding="utf-8"
    )
    write_registry(
        repo,
        [
            {
                "id": "messaging.draft_email",
                "value": "messaging.{tenant}.draft_email",
                "files": ["app/services/publisher.ts"],
                "status": "active",
            },
            {
                "id": "messaging.composed",
                "value": "messaging.{tenant}.draft_email",
                "anchor": "createEmailDraft",
                "files": ["app/services/composed.ts"],
                "status": "active",
            },
        ],
    )
    assert check(repo) == 1
    out = capsys.readouterr().out
    assert "value-absent" in out
    assert "createEmailDraft" in out


def test_rejects_a_stale_file_path(repo, capsys):
    (repo / "app" / "services" / "publisher.ts").unlink()
    assert check(repo) == 1
    assert "missing-file" in capsys.readouterr().out


# ── rule: markers and entries agree both ways ───────────────────────────────


def test_bare_contract_word_in_code_is_not_a_marker(repo, capsys):
    """`CORREOS_REQUESTS_COD_CONTRACT: z.string()` is code, not a marker.

    Without the comment-lead requirement it reported the contract id `z.string`.
    """
    (repo / "app" / "schema.ts").write_text(
        "const S = { CORREOS_REQUESTS_COD_CONTRACT: z.string().min(1) };\n", encoding="utf-8"
    )
    assert check(repo) == 0


def test_rejects_a_marker_with_no_registry_entry(repo, capsys):
    (repo / "app" / "other.ts").write_text(
        "// CONTRACT: messaging.invented\nconst x = 1;\n", encoding="utf-8"
    )
    assert check(repo) == 1
    assert "marker-unregistered" in capsys.readouterr().out


def test_warns_when_an_entry_has_no_marker(repo, capsys):
    """Without the marker, an agent editing the file sees nothing."""
    target = repo / "app" / "services" / "publisher.ts"
    target.write_text(
        target.read_text().replace("// CONTRACT: messaging.draft_email", "// publisher"),
        encoding="utf-8",
    )
    assert check(repo) == 0
    assert "marker-missing" in capsys.readouterr().out


# ── rule: lifecycle fields ──────────────────────────────────────────────────


def test_rejects_deprecated_without_replacement_or_deadline(repo, capsys):
    write_registry(
        repo,
        [
            {
                "id": "messaging.draft_email",
                "value": "messaging.{tenant}.draft_email",
                "files": ["app/services/publisher.ts"],
                "status": "deprecated",
            }
        ],
    )
    assert check(repo) == 1
    out = capsys.readouterr().out
    assert "replaced_by" in out and "remove_after" in out


def test_rejects_removed_without_approval(repo, capsys):
    write_registry(
        repo,
        [
            {
                "id": "messaging.draft_email",
                "value": "messaging.{tenant}.draft_email",
                "files": ["app/services/publisher.ts"],
                "status": "removed",
            }
        ],
    )
    assert check(repo) == 1
    assert "approved_by" in capsys.readouterr().out


def test_rejects_duplicate_ids(repo, capsys):
    entry = {
        "id": "messaging.draft_email",
        "value": "messaging.{tenant}.draft_email",
        "files": ["app/services/publisher.ts"],
    }
    write_registry(repo, [entry, dict(entry)])
    assert check(repo) == 1
    assert "duplicate" in capsys.readouterr().out


def test_rejects_an_unknown_kind(repo, capsys):
    write_registry(
        repo,
        [
            {
                "id": "messaging.draft_email",
                "kind": "vibes",
                "value": "messaging.{tenant}.draft_email",
                "files": ["app/services/publisher.ts"],
            }
        ],
    )
    assert check(repo) == 1
    assert "kind" in capsys.readouterr().out


def test_rejects_invalid_yaml(repo, capsys):
    (repo / "CONTRACTS.yaml").write_text("contracts: [unclosed\n", encoding="utf-8")
    assert check(repo) == 1


# ── push-time rules ─────────────────────────────────────────────────────────


def _commit(repo: Path, message: str) -> None:
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-qm", message)


def test_rejects_touching_surface_without_updating_the_registry(repo, capsys):
    target = repo / "app" / "services" / "publisher.ts"
    target.write_text(target.read_text() + "\n// tweak\n", encoding="utf-8")
    _commit(repo, "chore: tweak publisher")
    assert check(repo, "HEAD~1..HEAD") == 1
    assert "registry-not-updated" in capsys.readouterr().out


def test_rejects_a_missing_contract_change_trailer(repo, capsys):
    target = repo / "app" / "services" / "publisher.ts"
    target.write_text(target.read_text() + "\n// tweak\n", encoding="utf-8")
    write_registry(
        repo,
        [
            {
                "id": "messaging.draft_email",
                "value": "messaging.{tenant}.draft_email",
                "files": ["app/services/publisher.ts"],
                "status": "active",
                "note": "touched",
            }
        ],
    )
    _commit(repo, "chore: tweak publisher and registry")
    assert check(repo, "HEAD~1..HEAD") == 1
    assert "trailer-missing" in capsys.readouterr().out


def test_accepts_surface_change_with_registry_and_trailer(repo, capsys):
    target = repo / "app" / "services" / "publisher.ts"
    target.write_text(target.read_text() + "\n// tweak\n", encoding="utf-8")
    write_registry(
        repo,
        [
            {
                "id": "messaging.draft_email",
                "value": "messaging.{tenant}.draft_email",
                "files": ["app/services/publisher.ts"],
                "status": "active",
                "note": "touched",
            }
        ],
    )
    _commit(repo, "feat: tweak publisher\n\nContract-Change: migrate messaging.draft_email")
    assert check(repo, "HEAD~1..HEAD") == 0
    assert "OK" in capsys.readouterr().out


def test_rejects_editing_an_active_value_in_place(repo, capsys):
    """Rule 1, the load-bearing one: active values never mutate."""
    rename_in_code(repo, "draft_email", "draft_email_v2")
    write_registry(
        repo,
        [
            {
                "id": "messaging.draft_email",
                "value": "messaging.{tenant}.draft_email_v2",
                "files": ["app/services/publisher.ts"],
                "status": "active",
            }
        ],
    )
    _commit(repo, "feat: rename\n\nContract-Change: break messaging.draft_email")
    assert check(repo, "HEAD~1..HEAD") == 1
    assert "value-mutated" in capsys.readouterr().out


def test_accepts_an_in_place_break_with_a_complete_exception(repo, capsys):
    """The legitimate fast path for one operator, with evidence attached."""
    rename_in_code(repo, "draft_email", "draft_email_v2")
    write_registry(
        repo,
        [
            {
                "id": "messaging.draft_email",
                "value": "messaging.{tenant}.draft_email_v2",
                "files": ["app/services/publisher.ts"],
                "status": "active",
                "exception": {
                    "reason": "key was never consumed by anything in production",
                    "consumers_checked": "grep -rn draft_email ~/k8s -> only this repo",
                    "approved_by": "dani 2026-07-28",
                },
            }
        ],
    )
    _commit(repo, "fix: rename\n\nContract-Change: break messaging.draft_email")
    assert check(repo, "HEAD~1..HEAD") == 0


def test_rejects_an_incomplete_exception(repo, capsys):
    rename_in_code(repo, "draft_email", "draft_email_v2")
    write_registry(
        repo,
        [
            {
                "id": "messaging.draft_email",
                "value": "messaging.{tenant}.draft_email_v2",
                "files": ["app/services/publisher.ts"],
                "status": "active",
                "exception": {"reason": "felt like it"},
            }
        ],
    )
    _commit(repo, "fix: rename\n\nContract-Change: break messaging.draft_email")
    assert check(repo, "HEAD~1..HEAD") == 1
    out = capsys.readouterr().out
    assert "exception-incomplete" in out
    assert "approved_by" in out


def test_rejects_deleting_an_entry(repo, capsys):
    """Tombstones: a deleted entry erases the story a future grep needs."""
    (repo / "app" / "services" / "publisher.ts").write_text("// nothing\n", encoding="utf-8")
    write_registry(repo, [])
    _commit(repo, "chore: drop it\n\nContract-Change: remove messaging.draft_email")
    assert check(repo, "HEAD~1..HEAD") == 1
    assert "entry-deleted" in capsys.readouterr().out


def test_accepts_a_proper_deprecate_and_replace(repo, capsys):
    """The sanctioned way to break: new entry, old one deprecated, both present."""
    target = repo / "app" / "services" / "publisher.ts"
    target.write_text(
        "// CONTRACT: messaging.draft_email\n"
        "// CONTRACT: messaging.draft_email.v2\n"
        'export const OLD = `messaging.${tenant}.draft_email`;\n'
        'export const NEW = `messaging.${tenant}.draft_email_v2`;\n',
        encoding="utf-8",
    )
    write_registry(
        repo,
        [
            {
                "id": "messaging.draft_email",
                "value": "messaging.{tenant}.draft_email",
                "files": ["app/services/publisher.ts"],
                "status": "deprecated",
                "replaced_by": "messaging.draft_email.v2",
                "remove_after": "2026-12-31",
            },
            {
                "id": "messaging.draft_email.v2",
                "value": "messaging.{tenant}.draft_email_v2",
                "files": ["app/services/publisher.ts"],
                "status": "active",
            },
        ],
    )
    _commit(
        repo,
        "feat: dual-publish draft email\n\n"
        "Contract-Change: deprecate messaging.draft_email -> messaging.draft_email.v2",
    )
    assert check(repo, "HEAD~1..HEAD") == 0


def test_ignores_node_modules_when_hunting_markers(repo, capsys):
    vendored = repo / "node_modules" / "dep"
    vendored.mkdir(parents=True)
    (vendored / "index.js").write_text("// CONTRACT: vendored.junk\n", encoding="utf-8")
    assert check(repo) == 0
