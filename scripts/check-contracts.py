#!/usr/bin/env python3
"""Enforce the contract rules for any repo carrying a CONTRACTS.yaml.

Merging straight to trunk with no pull requests means review cannot be the place
contract breaks are caught. This script is that place: it runs in the global
pre-push hook (covering Claude, Codex and a human equally) and again in CI as a
backstop for machines without the hook.

What a contract is, here: a value that breaks ANOTHER process when it changes,
invisibly to this repo's own tests — routing keys, message schemas, HTTP routes
other services call, KEDA queue names, console allowlists.

The rules it enforces (full text: skill `synapse-contracts`):

  1. The `value` of an `active` entry is never edited in place.
  2. A breaking change is a NEW `.vN+1` entry; the old one goes `deprecated`
     with `replaced_by` + `remove_after`.
  3. A commit touching contract surface updates CONTRACTS.yaml in the same push
     and carries a `Contract-Change: <action> <id>` trailer.
  4. Entries are never deleted; retiring code means `status: removed`.
  5. Going `deprecated` → `removed` needs `approved_by`.

Deliberate in-place breaks are allowed, but only with an `exception:` block
(reason, consumers_checked, approved_by) added in the same range — the fast path
for one operator, with the evidence recorded rather than assumed.

With `--range` the tree checks (schema, value-absent, missing-file,
marker-unregistered, lifecycle) are attributed to the push: each finding is
compared against the same findings computed on the BASE commit's tree (the left
side of the range), and only findings that do not exist there block. Pre-existing
debt is printed as a counted, non-blocking note — visible, but it does not
blacklist every push in a repo that accumulated findings before the gate existed
(INFRA-587: dgx-infra carried 111, so no branch push could pass and sessions
reached for --no-verify, which kills the gate). Without `--range` the full tree
is validated and everything blocks: that is the CI backstop, unchanged.

Usage:
    check-contracts.py                        # validate the working tree
    check-contracts.py --range HEAD~3..HEAD   # push rules + blame attribution
    check-contracts.py --repo /path/to/repo
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - surfaced as a clear message, not a crash
    print(
        "check-contracts: PyYAML is required (pip install pyyaml)",
        file=sys.stderr,
    )
    raise SystemExit(2) from None

REGISTRY_FILENAME = "CONTRACTS.yaml"
# The marker must lead with a comment token. A bare `CONTRACT:` also matches
# ordinary code — `CORREOS_REQUESTS_COD_CONTRACT: z.string()` in
# skirmshop-labels reported the contract id `z.string`.
MARKER_RE = re.compile(r"(?:#|//|/\*|\*|--|<!--)\s*CONTRACT:\s*([a-z0-9][a-z0-9._-]*)")
# The same rule as an ERE, for `git grep` over a commit's tree (INFRA-587: the
# base side of a range is never checked out, so markers are read from git).
MARKER_ERE = (
    r"(#|//|/\*|\*|--|<!--)[[:space:]]*CONTRACT:[[:space:]]*[a-z0-9][a-z0-9._-]*"
)
TRAILER_RE = re.compile(
    r"^Contract-Change:\s*(add|deprecate|remove|migrate|break)\s+(\S+)", re.M
)
VALID_STATUS = {"active", "deprecated", "removed"}
VALID_KINDS = {
    "routing-key",
    "cloudevent",
    "schema",
    "http-route",
    "queue",
    "allowlist",
    "workflow-file",
    # Kinds the registries actually carry (INFRA-587, evidence in dgx-infra's
    # CONTRACTS.yaml): a Prometheus metric name, the shape of a data file, a
    # Redis key namespace, an MCP tool surface and a batch job kind are each a
    # value that breaks another process when it changes.
    "metric",
    "file-schema",
    "redis-key",
    "mcp-tools",
    "job-kind",
}
# `.contracts-checker` is where the Contract surface job checks this repo out
# inside the consumer's workspace; its test file is a pile of fixture markers no
# consumer registry declares (k8s-litellm#124).
SKIP_DIRS = {".git", "node_modules", ".venv", "dist", "build", "__pycache__", ".next", ".contracts-checker"}
TEXT_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".yaml", ".yml", ".json",
    ".toml", ".sh", ".md", ".sql", ".tf",
}


@dataclass
class Finding:
    code: str
    message: str
    hint: str | None = None
    # Stable identity for blame attribution: (code, contract id, path) with NO
    # line numbers — lines shift between the base commit and the pushed tree,
    # and a key that moves would blame pre-existing debt on an innocent push.
    key: tuple[str, str, str] = ()

    def render(self) -> str:
        out = f"  [{self.code}] {self.message}"
        if self.hint:
            out += f"\n      → {self.hint}"
        return out


@dataclass
class Report:
    failures: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    ).stdout


def _read_file(repo: Path, rel: str, rev: str | None = None) -> str | None:
    """Text of a path in the working tree, or in commit `rev` when given."""
    if rev is None:
        path = repo / rel
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    if rel.endswith("/"):
        return None  # a directory is never a file, in either tree
    r = subprocess.run(  # noqa: S603
        ["git", "cat-file", "blob", f"{rev}:{rel}"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    # `cat-file blob` (not `show`): a tree path must fail here exactly as a
    # directory fails `is_file()` above, or the same stale `files:` entry would
    # key as value-absent in the base and missing-file in the worktree.
    return r.stdout if r.returncode == 0 else None


def _entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    contracts = data.get("contracts")
    if isinstance(contracts, list):
        return [c for c in contracts if isinstance(c, dict)]
    if isinstance(contracts, dict):
        return [
            {"id": name, **spec} for name, spec in contracts.items() if isinstance(spec, dict)
        ]
    return []


# ── tree validation (working tree, or the tree of one commit) ───────────────


def validate_schema(report: Report, entries: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for spec in entries:
        cid = str(spec.get("id") or "")
        if not cid:
            report.failures.append(
                Finding("schema", f"entry with no `id`: {spec!r}", key=("schema", "", ""))
            )
            continue
        if cid in seen:
            report.failures.append(
                Finding("schema", f"duplicate contract id {cid!r}", key=("schema", cid, "duplicate"))
            )
        seen.add(cid)
        status = spec.get("status", "active")
        if status not in VALID_STATUS:
            report.failures.append(
                Finding(
                    "schema",
                    f"{cid}: status {status!r} is not one of {sorted(VALID_STATUS)}",
                    key=("schema", cid, "status"),
                )
            )
        kind = spec.get("kind")
        if kind and kind not in VALID_KINDS:
            report.failures.append(
                Finding(
                    "schema",
                    f"{cid}: kind {kind!r} is not one of {sorted(VALID_KINDS)}",
                    key=("schema", cid, "kind"),
                )
            )
        if not spec.get("value"):
            report.failures.append(
                Finding("schema", f"{cid}: no `value`", key=("schema", cid, "value"))
            )
        if status == "deprecated":
            for required in ("replaced_by", "remove_after"):
                if not spec.get(required):
                    report.failures.append(
                        Finding(
                            "lifecycle",
                            f"{cid} is deprecated but has no `{required}`",
                            "deprecation is a promise with a deadline, not a parking spot",
                            key=("lifecycle", cid, required),
                        )
                    )
        if status == "removed" and not spec.get("approved_by"):
            report.failures.append(
                Finding(
                    "lifecycle",
                    f"{cid} is removed without `approved_by`",
                    "removal needs recorded confirmation; the tombstone stays either way",
                    key=("lifecycle", cid, "approved_by"),
                )
            )


def _value_pattern(value: str) -> re.Pattern[str]:
    """Compile a contract value into a token-exact search pattern.

    Two traps, both learned the hard way:

    - A `{tenant}`-style placeholder is filled at runtime, so the template is
      never in the source verbatim. What fills it may itself contain dots —
      skirmshop-labels writes `` `messaging.${config.tenant}.send` `` — so the
      placeholder must not be restricted to a single dotless token.
    - Substring matching is not enough. `messaging.{tenant}.draft_email` would
      happily match a file that now says `draft_email_v2`, so a rename that
      merely APPENDS — the most common kind — would pass unnoticed. The trailing
      boundary is what makes this check real.
    """
    parts = re.split(r"\{[a-z_]+\}", value)
    body = r"[^\s\"'`]+?".join(re.escape(part) for part in parts)
    return re.compile(rf"(?<![A-Za-z0-9_]){body}(?![A-Za-z0-9_])")


def validate_values_present(
    report: Report, repo: Path, entries: list[dict[str, Any]], rev: str | None = None
) -> None:
    """Every active entry's value must still appear in the files it claims.

    This single check is what would have caught the 2026-07-28 incident: the
    consumer's routing key was changed while the registry still said the old
    value lived in that file.
    """
    for spec in entries:
        if spec.get("status", "active") != "active":
            continue
        value = str(spec.get("value") or "")
        files = spec.get("files") or []
        if not value or not files:
            continue
        # Many publishers never contain their routing key as a literal — it is
        # composed from parts at runtime (`f"{adapter}.{TENANT}.{action}"`,
        # `createEmailDraft(...)`). That ungreppability is precisely why the
        # 2026-07-28 break went unnoticed for weeks, so those entries declare an
        # `anchor`: the literal that DOES appear and whose disappearance means
        # the call site moved or was renamed.
        anchor = spec.get("anchor")
        pattern = _value_pattern(str(anchor) if anchor else value)
        described = f"anchor {anchor!r} for {value!r}" if anchor else f"value {value!r}"
        for rel in files:
            text = _read_file(repo, str(rel), rev)
            if text is None:
                report.failures.append(
                    Finding(
                        "missing-file",
                        f"{spec['id']}: listed file {rel} does not exist",
                        "update `files:` if the code moved — a stale path checks nothing",
                        key=("missing-file", str(spec.get("id") or ""), str(rel)),
                    )
                )
                continue
            if not pattern.search(text):
                report.failures.append(
                    Finding(
                        "value-absent",
                        f"{spec['id']}: {described} no longer appears in {rel}",
                        "if it was renamed, that is a breaking change: add a new .vN+1 entry "
                        "and deprecate this one instead of editing it",
                        key=("value-absent", str(spec.get("id") or ""), str(rel)),
                    )
                )


def _iter_source_files(repo: Path):
    for path in repo.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        if SKIP_DIRS & set(path.parts):
            continue
        yield path


def _marker_map(repo: Path, rev: str | None = None) -> dict[str, str]:
    """cid -> the first file that marks it, without a line number.

    Over the working tree the files are read directly; over a commit the markers
    come from `git grep` so the base tree never has to be materialised.
    """
    found: dict[str, str] = {}
    if rev is None:
        for path in _iter_source_files(repo):
            if path.name == REGISTRY_FILENAME:
                continue
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                for cid in MARKER_RE.findall(line):
                    found.setdefault(cid, str(path.relative_to(repo)))
        return found
    out = _git(
        repo, "grep", "-I", "-n", "-E", MARKER_ERE, rev,
        "--", *(f"*{suffix}" for suffix in sorted(TEXT_SUFFIXES)),
    )
    prefix = f"{rev}:"
    for line in out.splitlines():
        # `git grep -n <rev>` prints "<rev>:<path>:<line>:<content>"
        if line.startswith(prefix):
            line = line[len(prefix):]
        path, _, rest = line.partition(":")
        _, _, content = rest.partition(":")
        if path == REGISTRY_FILENAME or path.endswith("/" + REGISTRY_FILENAME):
            continue
        for cid in MARKER_RE.findall(content):
            found.setdefault(cid, path)
    return found


def validate_markers(
    report: Report, repo: Path, entries: list[dict[str, Any]], rev: str | None = None
) -> None:
    """`# CONTRACT: <id>` markers and registry entries must agree both ways."""
    known = {spec["id"] for spec in entries if spec.get("id")}
    found = _marker_map(repo, rev)
    for cid, where in sorted(found.items()):
        if cid not in known:
            report.failures.append(
                Finding(
                    "marker-unregistered",
                    f"{where} marks contract {cid!r}, which has no entry in {REGISTRY_FILENAME}",
                    "add the entry, or fix the id in the marker",
                    key=("marker-unregistered", cid, where),
                )
            )
    for cid in sorted(known - set(found)):
        spec = next(s for s in entries if s.get("id") == cid)
        if spec.get("status", "active") != "active":
            continue
        report.warnings.append(
            Finding(
                "marker-missing",
                f"{cid} has no `# CONTRACT:` marker in the code",
                "the marker is what an agent editing the file actually sees; add one",
                key=("marker-missing", cid, ""),
            )
        )


def collect_tree_findings(
    repo: Path, rev: str | None = None
) -> tuple[Report, list[dict[str, Any]]]:
    """Run the three tree validators over the working tree, or over commit `rev`."""
    text = _read_file(repo, REGISTRY_FILENAME, rev)
    if text is None:
        return Report(), []
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return Report(), []
    entries = _entries(data)
    report = Report()
    validate_schema(report, entries)
    validate_values_present(report, repo, entries, rev)
    validate_markers(report, repo, entries, rev)
    return report, entries


# ── push-time rules ─────────────────────────────────────────────────────────


def _changed_files(repo: Path, rev_range: str) -> set[str]:
    out = _git(repo, "diff", "--name-only", rev_range)
    return {line.strip() for line in out.splitlines() if line.strip()}


def _contract_files(repo: Path, entries: list[dict[str, Any]]) -> set[str]:
    listed = {str(f) for spec in entries for f in (spec.get("files") or [])}
    marked = set()
    for path in _iter_source_files(repo):
        if path.name == REGISTRY_FILENAME:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if MARKER_RE.search(text):
            marked.add(str(path.relative_to(repo)))
    return listed | marked


def _registry_paths(data: dict[str, Any]) -> set[str]:
    """Files that count as "the registry was updated"."""
    paths = {REGISTRY_FILENAME}
    extra = data.get("registry_files") or []
    paths.update(str(p) for p in extra)
    return paths


def validate_range(
    report: Report, repo: Path, data: dict[str, Any], entries: list[dict[str, Any]], rev_range: str
) -> None:
    changed = _changed_files(repo, rev_range)
    if not changed:
        return
    surface = _contract_files(repo, entries)
    touched_surface = sorted(changed & surface)
    registry_paths = _registry_paths(data)
    touched_registry = bool(changed & registry_paths)
    log = _git(repo, "log", "--format=%B%x00", rev_range)
    trailers = TRAILER_RE.findall(log)

    if touched_surface and not touched_registry:
        report.failures.append(
            Finding(
                "registry-not-updated",
                "this push changes contract surface but does not touch "
                f"{'/'.join(sorted(registry_paths))}: {', '.join(touched_surface)}",
                "record the change in the registry in the SAME push, or move the edit out "
                "of the contract surface",
            )
        )
    if touched_surface and not trailers:
        report.failures.append(
            Finding(
                "trailer-missing",
                "no `Contract-Change:` trailer in this push, but contract surface changed",
                "add `Contract-Change: <add|deprecate|remove|migrate|break> <id>` to the "
                "commit message — `git log --grep` of that trailer is the audit trail",
            )
        )

    # Rule 1: an active entry's `value` must not be edited in place.
    if not (changed & registry_paths):
        return
    for path in sorted(changed & registry_paths):
        before = _git(repo, "show", f"{rev_range.split('..')[0]}:{path}")
        if not before.strip():
            continue
        try:
            old = yaml.safe_load(before) or {}
        except yaml.YAMLError:
            continue
        old_by_id = {s["id"]: s for s in _entries(old) if s.get("id")}
        new_by_id = {s["id"]: s for s in entries if s.get("id")}
        for cid, old_spec in old_by_id.items():
            new_spec = new_by_id.get(cid)
            if new_spec is None:
                report.failures.append(
                    Finding(
                        "entry-deleted",
                        f"{cid} was deleted from the registry",
                        "entries are tombstones: set `status: removed` instead of deleting, so a "
                        "grep of the old name still explains itself",
                    )
                )
                continue
            if old_spec.get("status", "active") != "active":
                continue
            if old_spec.get("value") == new_spec.get("value"):
                continue
            if new_spec.get("exception"):
                missing = [
                    field_name
                    for field_name in ("reason", "consumers_checked", "approved_by")
                    if not (new_spec["exception"] or {}).get(field_name)
                ]
                if missing:
                    report.failures.append(
                        Finding(
                            "exception-incomplete",
                            f"{cid}: in-place value change has an `exception:` block missing "
                            f"{', '.join(missing)}",
                            "the exception path is fast but it is evidence-bearing",
                        )
                    )
                continue
            report.failures.append(
                Finding(
                    "value-mutated",
                    f"{cid}: the value of an active entry was changed in place "
                    f"({old_spec.get('value')!r} → {new_spec.get('value')!r})",
                    "breaking change = NEW entry .vN+1 + deprecate the old one. To break in "
                    "place deliberately, add an `exception:` block with reason, "
                    "consumers_checked and approved_by",
                )
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--range",
        dest="rev_range",
        help="commit range being pushed (e.g. origin/main..HEAD); enables the push rules "
        "and attributes tree findings to the range",
    )
    parser.add_argument("--report-only", action="store_true", help="always exit 0")
    args = parser.parse_args()

    repo = args.repo.resolve()
    registry_path = repo / REGISTRY_FILENAME
    if not registry_path.is_file():
        return 0  # repo declares no contract surface; nothing to enforce

    try:
        data = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"FAIL: {REGISTRY_FILENAME} is not valid YAML: {exc}", file=sys.stderr)
        return 1
    entries = _entries(data)

    report, _ = collect_tree_findings(repo)

    preexisting: list[Finding] = []
    if args.rev_range:
        base = args.rev_range.split("..", 1)[0].rstrip(".")
        base_keys: set[tuple[str, str, str]] = set()
        if base and _git(repo, "rev-parse", "--verify", "-q", f"{base}^{{commit}}").strip():
            base_report, _ = collect_tree_findings(repo, rev=base)
            base_keys = {f.key for f in base_report.failures}
        else:
            print(
                f"check-contracts: base {base!r} of {args.rev_range!r} is not a commit here; "
                "every tree finding blocks as before",
                file=sys.stderr,
            )
        fresh: list[Finding] = []
        for finding in report.failures:
            if finding.key and finding.key in base_keys:
                preexisting.append(finding)
            else:
                fresh.append(finding)
        report.failures = fresh
        validate_range(report, repo, data, entries, args.rev_range)

    if report.warnings:
        print(f"contracts: {len(report.warnings)} note(s) in {repo.name}:")
        for finding in report.warnings:
            print(finding.render())
        print()

    if preexisting:
        print(
            f"contracts: {len(preexisting)} pre-existing tree finding(s) in {repo.name} — "
            "already in the base commit, not blamed on this push (the debt stays visible):"
        )
        for finding in preexisting:
            print(finding.render())
        print()

    if report.failures:
        print(f"CONTRACT CHECK FAILED — {len(report.failures)} problem(s) in {repo.name}:")
        for finding in report.failures:
            print(finding.render())
        print("\nRules and the exception path: skill `synapse-contracts`.")
        return 0 if args.report_only else 1

    print(f"contracts: OK ({len(entries)} entries in {repo.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
