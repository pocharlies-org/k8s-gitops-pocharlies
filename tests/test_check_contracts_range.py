#!/usr/bin/env python3
"""Blame attribution for `--range` (INFRA-587).

The gate died of its own strictness: dgx-infra carried 111 pre-existing tree
findings, `--range` reported them on every push, and sessions answered with
`--no-verify`. These tests pin the fix: with `--range`, a pre-existing finding
is a counted note and the push passes; a finding the range introduces still
blocks; without `--range` the whole tree blocks as before (the CI backstop).

Run: python3 -m pytest tests/test_check_contracts_range.py -q
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

CHECKER = Path(__file__).resolve().parents[1] / "scripts" / "check-contracts.py"


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return r.stdout.strip()


def _check(repo: Path, rev_range: str | None = None) -> tuple[int, str]:
    argv = [sys.executable, str(CHECKER), "--repo", str(repo)]
    if rev_range:
        argv += ["--range", rev_range]
    r = subprocess.run(argv, capture_output=True, text=True, check=False)
    return r.returncode, r.stdout + r.stderr


def _registry(contracts: list[dict]) -> str:
    return yaml.safe_dump({"version": 1, "contracts": contracts}, sort_keys=False)


@pytest.fixture
def repo_with_debt(tmp_path: Path) -> Path:
    """A committed repo carrying one pre-existing violation: value-absent.

    `messaging.gone.v1` claims app/gone.ts holds its value; the file exists and
    says nothing of the kind. The violation is in the FIRST commit, so it is
    base debt, not something a later push introduced.
    """
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "publisher.ts").write_text(
        "// CONTRACT: messaging.draft_email\n"
        'export const KEY = `messaging.${tenant}.draft_email`;\n',
        encoding="utf-8",
    )
    (tmp_path / "app" / "gone.ts").write_text("const unrelated = 1;\n", encoding="utf-8")
    (tmp_path / "CONTRACTS.yaml").write_text(
        _registry(
            [
                {
                    "id": "messaging.draft_email",
                    "kind": "routing-key",
                    "value": "messaging.{tenant}.draft_email",
                    "files": ["app/publisher.ts"],
                    "status": "active",
                },
                {
                    "id": "messaging.gone.v1",
                    "kind": "routing-key",
                    "value": "messaging.{tenant}.gone",
                    "files": ["app/gone.ts"],
                    "status": "active",
                },
            ]
        ),
        encoding="utf-8",
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "initial: one healthy entry, one stale entry")
    return tmp_path


def test_preexisting_finding_is_a_note_with_range(repo_with_debt: Path) -> None:
    """The INFRA-587 case: an innocent push in a repo with old debt must pass."""
    _git(repo_with_debt, "checkout", "-qb", "docs-only")
    (repo_with_debt / "docs").mkdir()
    (repo_with_debt / "docs" / "note.md").write_text("unrelated\n", encoding="utf-8")
    _git(repo_with_debt, "add", "-A")
    _git(repo_with_debt, "commit", "-qm", "docs: a note")
    rc, out = _check(repo_with_debt, "main..docs-only")
    assert rc == 0, out
    assert "pre-existing" in out and "value-absent" in out


def test_without_range_the_tree_still_blocks(repo_with_debt: Path) -> None:
    """No --range means the full-tree backstop: the debt blocks, unchanged."""
    rc, out = _check(repo_with_debt)
    assert rc == 1, out
    assert "value-absent" in out


def test_new_finding_blocks_with_range(repo_with_debt: Path) -> None:
    """A range that introduces a violation is still refused."""
    _git(repo_with_debt, "checkout", "-qb", "new-debt")
    registry = yaml.safe_load((repo_with_debt / "CONTRACTS.yaml").read_text())
    registry["contracts"].append(
        {
            "id": "messaging.never.v1",
            "kind": "routing-key",
            "value": "messaging.{tenant}.never",
            "files": ["app/never.ts"],  # never existed -> missing-file is NEW
            "status": "active",
        }
    )
    (repo_with_debt / "CONTRACTS.yaml").write_text(yaml.safe_dump(registry, sort_keys=False))
    _git(repo_with_debt, "add", "-A")
    _git(repo_with_debt, "commit", "-qm", "registry: entry for a file that does not exist")
    rc, out = _check(repo_with_debt, "main..new-debt")
    assert rc == 1, out
    assert "missing-file" in out
    assert "messaging.never.v1" in out


def test_line_shift_does_not_blame_the_push(tmp_path: Path) -> None:
    """The finding key carries no line numbers: lines move, debt stays debt.

    The range legitimately edits contract surface (registry + trailer), and in
    doing so shifts the line of an OLD unregistered marker. With line numbers in
    the key that debt would look new and block an honest push.
    """
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "publisher.ts").write_text(
        "// CONTRACT: messaging.draft_email\n"
        'export const KEY = `messaging.${tenant}.draft_email`;\n',
        encoding="utf-8",
    )
    (tmp_path / "app" / "stray.ts").write_text(
        "// CONTRACT: stray.id\nconst x = 1;\n", encoding="utf-8"
    )
    (tmp_path / "CONTRACTS.yaml").write_text(
        _registry(
            [
                {
                    "id": "messaging.draft_email",
                    "kind": "routing-key",
                    "value": "messaging.{tenant}.draft_email",
                    "files": ["app/publisher.ts"],
                    "status": "active",
                }
            ]
        ),
        encoding="utf-8",
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "initial: healthy entry + stray marker")
    _git(tmp_path, "checkout", "-qb", "shift")
    pub = tmp_path / "app" / "publisher.ts"
    pub.write_text(pub.read_text() + "\n// tweak\n", encoding="utf-8")
    (tmp_path / "app" / "stray.ts").write_text(
        "\n\n\n\n\n// CONTRACT: stray.id\nconst x = 1;\n", encoding="utf-8"
    )
    registry = yaml.safe_load((tmp_path / "CONTRACTS.yaml").read_text())
    registry["contracts"][0]["note"] = "touched"
    (tmp_path / "CONTRACTS.yaml").write_text(yaml.safe_dump(registry, sort_keys=False))
    _git(tmp_path, "add", "-A")
    _git(
        tmp_path, "commit", "-qm",
        "feat: tweak publisher\n\nContract-Change: migrate messaging.draft_email",
    )
    rc, out = _check(tmp_path, "main..shift")
    assert rc == 0, out
    assert "marker-unregistered" in out and "pre-existing" in out


def test_push_rules_still_fire_with_range(repo_with_debt: Path) -> None:
    """Attribution changed nothing about the push rules themselves."""
    _git(repo_with_debt, "checkout", "-qb", "surface")
    target = repo_with_debt / "app" / "publisher.ts"
    target.write_text(target.read_text() + "\n// touched\n", encoding="utf-8")
    _git(repo_with_debt, "add", "-A")
    _git(repo_with_debt, "commit", "-qm", "chore: touch contract surface")
    rc, out = _check(repo_with_debt, "main..surface")
    assert rc == 1, out
    assert "registry-not-updated" in out and "trailer-missing" in out


def test_unknown_kinds_are_known(tmp_path: Path) -> None:
    """The kinds real registries carry must not be schema failures (INFRA-587)."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / "a.py").write_text("whatever = 1\n", encoding="utf-8")
    (tmp_path / "CONTRACTS.yaml").write_text(
        _registry(
            [
                {
                    "id": f"sample.{kind}.v1",
                    "kind": kind,
                    "value": "whatever",
                    "files": ["a.py"],
                    "status": "active",
                }
                for kind in ("metric", "file-schema", "redis-key", "mcp-tools", "job-kind")
            ]
        ),
        encoding="utf-8",
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "initial")
    rc, out = _check(tmp_path)
    assert rc == 0, out
