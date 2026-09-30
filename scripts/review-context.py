#!/usr/bin/env python3
"""Build `.review/context.md`: the extra context PR-Agent reads next to the diff.

It only REPORTS facts. It does not judge contracts: the rules (in-place edits,
`.vN+1`, trailers, deletions) live in `scripts/check-contracts.py` and are not
re-implemented here. What this adds is what a reviewer of one repo cannot see:
who consumes the touched contract (Synapse registry), which other open PRs
touch the same files, and what the brain remembers (`local-ops`).

Sections, fixed and in this order (empty = `_ninguno_`):
  1 Contratos tocados · 2 Trailers Contract-Change · 3 Consumidores del registry
  4 PRs abiertas que solapan · 5 Memoria local-ops · 6 Degradaciones

Exit codes: 0 (also when a source is missing: it is listed in section 6),
2 invalid usage, 4 on 401/403 from any API. No other code.
Tokens come from the environment only (GH_TOKEN, BRAIN_CI_KEY) and are never
printed. Model calls: none.

Usage:
    review-context.py --base origin/main --head HEAD --registry <registry.yaml>
    review-context.py --dry-run --repo x/y --pr 1      # no git, no network
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:  # PyYAML is optional: without it the contract sections degrade, exit 0.
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

SECTIONS = (
    "Contratos tocados",
    "Trailers Contract-Change",
    "Consumidores del registry",
    "PRs abiertas que solapan",
    "Memoria local-ops",
    "Degradaciones",
)
NONE = "_ninguno_"
MAX_BYTES = 20 * 1024
DEFAULT_REGISTRY = "./_synapse/libs/synapse-contracts/registry.yaml"
DEFAULT_BRAIN_URL = "http://skirmshop-brain.skirmshop-brain-prod.svc.cluster.local"
BRAIN_INSTANCE = "local-ops"
CONTRACTS_FILE = "CONTRACTS.yaml"
DRYRUN_FIXTURE = Path(__file__).resolve().parent.parent / "tests/fixtures/review-context/dry-run"
MARKER_RE = re.compile(r"(?:#|//|/\*|\*|--|<!--)\s*CONTRACT:\s*([a-z0-9][a-z0-9._-]*)")
TRAILER_RE = re.compile(r"^Contract-Change:\s*(\w+)\s+(\S+)", re.M)
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)")
HTTP_TIMEOUT = 15
MAX_OPEN_PRS = 30
MAX_MEMORY = 5


class AuthError(Exception):
    """401/403 from an API: the only failure that is not a degradation."""

    def __init__(self, source: str, code: int):
        super().__init__(f"{source} respondió HTTP {code}")
        self.source = source


class Degraded(Exception):
    pass


# ── git ─────────────────────────────────────────────────────────────────────


def git(workdir: Path, *args: str) -> str:
    proc = subprocess.run(  # noqa: S603
        ["git", *args], cwd=workdir, capture_output=True, text=True, check=False, timeout=60
    )
    if proc.returncode != 0:
        raise Degraded(f"git {args[0]}: {proc.stderr.strip()[:200]}")
    return proc.stdout


def load_yaml(text: str) -> Any:
    if yaml is None:
        raise Degraded("PyYAML no disponible")
    return yaml.safe_load(text) or {}


def contract_entries(data: Any) -> dict[str, dict[str, Any]]:
    contracts = data.get("contracts") if isinstance(data, dict) else None
    if isinstance(contracts, list):
        return {c["id"]: c for c in contracts if isinstance(c, dict) and c.get("id")}
    if isinstance(contracts, dict):
        return {k: v for k, v in contracts.items() if isinstance(v, dict)}
    return {}


def contracts_at(workdir: Path, rev: str) -> dict[str, dict[str, Any]]:
    try:
        return contract_entries(load_yaml(git(workdir, "show", f"{rev}:{CONTRACTS_FILE}")))
    except Degraded as exc:
        if "PyYAML" in str(exc):
            raise
        return {}  # the file does not exist at that revision


# ── section 1: contracts touched ────────────────────────────────────────────


def touched_from_registry_file(workdir: Path, base: str, head: str) -> list[dict[str, Any]]:
    before, after = contracts_at(workdir, base), contracts_at(workdir, head)
    out: list[dict[str, Any]] = []
    for cid, new in after.items():
        old = before.get(cid)
        facts: list[str] = []
        if old is None:
            facts.append("entrada añadida")
        else:
            if old.get("value") != new.get("value"):
                facts.append(f"value cambió: `{old.get('value')}` → `{new.get('value')}`")
            if old.get("status") != new.get("status"):
                facts.append(f"status: {old.get('status')} → {new.get('status')}")
        if "exception" in new and (old is None or "exception" not in old):
            facts.append("bloque exception: presente en el rango")
        if facts:
            out.append({"id": cid, "file": CONTRACTS_FILE, "line": "", "facts": facts,
                        "value": new.get("value"), "old_value": (old or {}).get("value")})
    for cid, old in before.items():
        if cid not in after:
            out.append({"id": cid, "file": CONTRACTS_FILE, "line": "",
                        "facts": ["entrada ausente en head"], "value": old.get("value")})
    return out


def touched_from_markers(workdir: Path, base: str, head: str) -> list[dict[str, Any]]:
    diff = git(workdir, "diff", "--unified=0", f"{base}...{head}")
    out, path, line = [], "", 0
    for raw in diff.splitlines():
        if raw.startswith("+++ b/"):
            path = raw[6:]
        elif (m := HUNK_RE.match(raw)):
            line = int(m.group(1))
        elif raw.startswith("+") and not raw.startswith("+++"):
            if (m := MARKER_RE.search(raw)):
                out.append({"id": m.group(1), "file": path, "line": line,
                            "facts": ["marca `# CONTRACT:` en líneas añadidas"], "value": None})
            line += 1
    return out


# ── section 2: trailers ─────────────────────────────────────────────────────


def trailers(workdir: Path, base: str, head: str) -> list[tuple[str, str, str]]:
    log = git(workdir, "log", "--format=%H%x00%B%x01", f"{base}..{head}")
    found = []
    for chunk in log.split("\x01"):
        if "\x00" not in chunk:
            continue
        sha, body = chunk.strip().split("\x00", 1)
        for m in TRAILER_RE.finditer(body):
            found.append((sha[:10], m.group(1), m.group(2)))
    return found


# ── section 3: consumers from the Synapse registry (offline, sparse checkout) ─


def _walk(node: Any, name: str = ""):
    if isinstance(node, dict):
        yield name, node
        for k, v in node.items():
            yield from _walk(v, str(k))
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v, name)


def _pattern(key: str) -> re.Pattern[str]:
    return re.compile("^" + re.sub(r"\\\{[^}]*\\\}", r"[^.]+", re.escape(key)) + "$")


def registry_consumers(registry: Any, cid: str, *values: str | None) -> list[tuple[str, list[str], list[str]]]:
    needles = {n for n in (cid, *values) if n}
    hits = []
    for name, node in _walk(registry):
        if "consumers" not in node and "workflows" not in node:
            continue
        candidates = {name, str(node.get("key", "")), str(node.get("id", ""))} - {""}
        if any(_pattern(c).match(n) or c == n for c in candidates for n in needles):
            hits.append((str(node.get("key") or name), list(node.get("consumers") or []),
                         list(node.get("workflows") or [])))
    return hits


# ── HTTP ────────────────────────────────────────────────────────────────────


def http_json(source: str, url: str, headers: dict[str, str], body: dict | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Accept": "application/json", **headers}
    if data:
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:  # noqa: S310
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise AuthError(source, exc.code) from None
        raise Degraded(f"{source}: HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise Degraded(f"{source}: {type(exc).__name__}") from None


def open_prs(repo: str, pr: int | None, files: set[str], token: str) -> list[dict[str, Any]]:
    hdrs = {"Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28"}
    base = f"https://api.github.com/repos/{repo}"
    prs = http_json("github", f"{base}/pulls?state=open&per_page={MAX_OPEN_PRS}", hdrs)
    out = []
    for p in prs:
        if p.get("number") == pr:
            continue
        theirs = {f["filename"] for f in http_json(
            "github", f"{base}/pulls/{p['number']}/files?per_page=100", hdrs)}
        common = sorted(files & theirs)
        if common:
            out.append({"number": p["number"], "title": p.get("title", ""),
                        "branch": p.get("head", {}).get("ref", ""), "files": common})
    return out


def brain_memory(url: str, key: str, query: str) -> list[dict[str, str]]:
    resp = http_json("brain", f"{url.rstrip('/')}/instances/{BRAIN_INSTANCE}/search",
                     {"X-API-Key": key, "Authorization": f"Bearer {key}"},
                     {"query": query, "limit": MAX_MEMORY * 2})
    if resp.get("instance_id", BRAIN_INSTANCE) != BRAIN_INSTANCE:
        raise Degraded("brain: la respuesta no es de la instancia local-ops")
    hits = []
    for doc in resp.get("documents", []):  # `documents`, not `hits`
        meta = doc.get("metadata") or {}
        if meta.get("instance_id", BRAIN_INSTANCE) != BRAIN_INSTANCE:
            continue  # /search has no per-instance gate: filter the result too
        source = meta.get("source_id") or meta.get("source") or meta.get("adapter") or "brain"
        summary = " ".join(str(doc.get("text", "")).split())[:200]
        hits.append({"source": str(source), "summary": summary})
    return hits[:MAX_MEMORY]


# ── render ──────────────────────────────────────────────────────────────────


def render(ctx: dict[str, Any]) -> str:
    def lst(items: list[str]) -> str:
        return "\n".join(items) if items else NONE

    s1 = [f"- `{t['id']}` — {t['file']}{':' + str(t['line']) if t['line'] else ''}: "
          + "; ".join(t["facts"]) for t in ctx["touched"]]
    s2 = [f"- {sha} `{act} {cid}` — en CONTRACTS.yaml: {'sí' if in_local else 'no'}; "
          f"en registry: {'sí' if in_reg else 'no'}" for sha, act, cid, in_local, in_reg in ctx["trailers"]]
    s3 = []
    for cid, hits in ctx["consumers"].items():
        for key, consumers, workflows in hits:
            s3.append(f"- `{cid}` ↔ `{key}`: consumers: {', '.join(consumers) or '_ninguno_'}"
                      + (f"; workflows: {', '.join(workflows)}" if workflows else ""))
    s4 = [f"- #{p['number']} {p['title']} (`{p['branch']}`): {', '.join(p['files'])}"
          for p in ctx["prs"]]
    s5 = [f"- [{m['source']}] {m['summary']}" for m in ctx["memory"]]
    s6 = [f"- Aviso · `{src}`: {why}" for src, why in ctx["degraded"]]

    def build(mem: list[str], prs: list[str]) -> str:
        parts = ["# Contexto de revisión (hechos, sin juicio)\n"]
        for title, body in zip(SECTIONS, (lst(s1), lst(s2), lst(s3), lst(prs), lst(mem),
                                          lst(s6) if s6 else "_ninguna_")):
            parts.append(f"## {title}\n\n{body}\n")
        return "\n".join(parts)

    text = build(s5, s4)
    while len(text.encode()) > MAX_BYTES and (s5 or s4):  # trim memory and overlaps, never s6
        (s5 or s4).pop()
        text = build(s5, s4)
    return text


# ── main ────────────────────────────────────────────────────────────────────


def collect(args: argparse.Namespace) -> dict[str, Any]:
    ctx: dict[str, Any] = {"touched": [], "trailers": [], "consumers": {}, "prs": [],
                           "memory": [], "degraded": []}
    workdir = Path(args.workdir)

    def degrade(source: str, why: object) -> None:
        ctx["degraded"].append((source, str(why)))

    registry: Any = None
    try:
        registry = load_yaml(Path(args.registry).read_text())
    except Exception as exc:  # noqa: BLE001 - any read/parse failure is a degradation
        degrade("registry", f"{args.registry}: {type(exc).__name__}")

    if args.dry_run:
        canned = json.loads((Path(args.fixtures) / "dry-run.json").read_text())
        ctx["touched"] = canned["touched"]
        ctx["trailers"] = [tuple(t) for t in canned["trailers"]]
        ctx["prs"], ctx["memory"] = canned["prs"], canned["memory"]
    else:
        try:
            ctx["touched"] = touched_from_registry_file(workdir, args.base, args.head)
            ctx["touched"] += touched_from_markers(workdir, args.base, args.head)
            local = contracts_at(workdir, args.head)
            for sha, act, cid in trailers(workdir, args.base, args.head):
                in_reg = bool(registry) and bool(registry_consumers(registry, cid, None))
                ctx["trailers"].append((sha, act, cid, cid in local, in_reg))
        except Degraded as exc:
            degrade("git", exc)

    if registry:
        for t in ctx["touched"]:
            hits = registry_consumers(registry, t["id"], t.get("value"), t.get("old_value"))
            if hits:
                ctx["consumers"][t["id"]] = hits

    if args.dry_run:
        return ctx

    files = {t["file"] for t in ctx["touched"]}
    try:
        files |= set(git(workdir, "diff", "--name-only", f"{args.base}...{args.head}").split())
    except Degraded:
        pass
    token = os.environ.get("GH_TOKEN", "")
    if not (args.repo and token):
        degrade("github", "falta --repo o GH_TOKEN")
    else:
        try:
            ctx["prs"] = open_prs(args.repo, args.pr, files, token)
        except Degraded as exc:
            degrade("github", exc)

    key = os.environ.get("BRAIN_CI_KEY", "")
    if not key:
        degrade("brain", "sin BRAIN_CI_KEY")
    else:
        query = " ".join([args.repo or "", *sorted(t["id"] for t in ctx["touched"]), *sorted(files)[:10]])
        try:
            ctx["memory"] = brain_memory(os.environ.get("BRAIN_URL", DEFAULT_BRAIN_URL), key, query)
        except Degraded as exc:
            degrade("brain", exc)
    return ctx


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", help="owner/repo (open PRs and brain query)")
    p.add_argument("--pr", type=int)
    p.add_argument("--base", "--base-sha", dest="base")
    p.add_argument("--head", "--head-sha", dest="head")
    p.add_argument("--registry", default=DEFAULT_REGISTRY,
                   help="sparse checkout of synapse:libs/synapse-contracts/registry.yaml")
    p.add_argument("--out", default=".review/context.md")
    p.add_argument("--workdir", default=".", help="git checkout of the PR")
    p.add_argument("--dry-run", action="store_true", help="no git, no network: canned fixtures")
    p.add_argument("--fixtures", default=str(DRYRUN_FIXTURE), help=argparse.SUPPRESS)
    return p


def base_head_from_event(args: argparse.Namespace) -> None:
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or not Path(path).is_file():
        return
    pr = (json.loads(Path(path).read_text()).get("pull_request") or {})
    args.base = args.base or (pr.get("base") or {}).get("sha")
    args.head = args.head or (pr.get("head") or {}).get("sha")
    args.pr = args.pr or pr.get("number")


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2  # --help is fine; any other parse error is usage
    if not args.dry_run:
        base_head_from_event(args)
        if not (args.base and args.head):
            print("review-context: faltan --base/--head (o GITHUB_EVENT_PATH)", file=sys.stderr)
            return 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        ctx = collect(args)
    except AuthError as exc:
        # No misleading partial context: only section 6 says what failed.
        empty = {"touched": [], "trailers": [], "consumers": {}, "prs": [], "memory": [],
                 "degraded": [(exc.source, f"{exc} — credencial rechazada")]}
        out.write_text(render(empty))
        print(f"review-context: {exc}", file=sys.stderr)
        return 4
    out.write_text(render(ctx))
    print(f"review-context: {out} ({len(ctx['degraded'])} degradaciones)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
