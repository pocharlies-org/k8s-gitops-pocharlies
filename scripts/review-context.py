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

Beside `--out` it also writes `contract-findings.json`: the deterministic list of
high-severity contract findings — a `value` that changed in place, with no
`Contract-Change` trailer for that id and no `exception` block — each one with the
file and the line of the changed `value` in the head tree. The CI (scripts/
review-distribute.py) publishes those as inline review comments through the GitHub
API, so the finding no longer depends on the model obeying its instructions
(seguimiento D del arquitecto, INFRA-332).

Exit codes: 0 (also when a source is missing: it is listed in section 6),
2 invalid usage, 4 on 401/403 from any API. No other code.
Tokens come from the environment only (GH_TOKEN, BRAIN_CI_KEY) and are never
printed. Model calls: none.
The HTTP client and the AuthError/Degraded rule are shared with the rest of the
review pipeline in `scripts/review_http.py`.

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
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))  # el módulo común vive junto a este script
from review_http import AuthError, Degraded, github_headers, request  # noqa: E402

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

VALUE_LINE_RE = re.compile(r"^\s*value:\s*\S")
ENTRY_ID_RE = re.compile(r"^\s*-\s+id:\s*(\S+)\s*$")


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


def value_line(text: str, cid: str) -> int | None:
    """Nº de línea (1-based, en el texto de head) del `value:` de la entrada `cid`.

    Búsqueda de línea sobre el texto crudo: el inline de GitHub ancla por número de
    línea del fichero, y PyYAML no la conserva."""
    inside = False
    for n, raw in enumerate(text.splitlines(), 1):
        m = ENTRY_ID_RE.match(raw)
        if m:
            inside = m.group(1) == cid
        elif inside and VALUE_LINE_RE.match(raw):
            return n
    return None


def touched_from_registry_file(workdir: Path, base: str, head: str) -> list[dict[str, Any]]:
    before, after = contracts_at(workdir, base), contracts_at(workdir, head)
    out: list[dict[str, Any]] = []
    head_text: str | None = None
    for cid, new in after.items():
        old = before.get(cid)
        facts: list[str] = []
        line = ""
        if old is None:
            facts.append("entrada añadida")
        else:
            if old.get("value") != new.get("value"):
                facts.append(f"value cambió: `{old.get('value')}` → `{new.get('value')}`")
                # la línea del value en head: el ancla del comentario en línea determinista
                if head_text is None:
                    try:
                        head_text = git(workdir, "show", f"{head}:{CONTRACTS_FILE}")
                    except Degraded:
                        head_text = ""
                if (n := value_line(head_text, cid)) is not None:
                    line = str(n)
            if old.get("status") != new.get("status"):
                facts.append(f"status: {old.get('status')} → {new.get('status')}")
        if "exception" in new and (old is None or "exception" not in old):
            facts.append("bloque exception: presente en el rango")
        if facts:
            out.append({"id": cid, "file": CONTRACTS_FILE, "line": line, "facts": facts,
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


# ── HTTP (cliente y clasificación de errores: scripts/review_http.py) ──────


def open_prs(repo: str, pr: int | None, files: set[str], token: str) -> list[dict[str, Any]]:
    hdrs = github_headers(token)
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    base = f"{api}/repos/{repo}"
    prs = request(f"{base}/pulls?state=open&per_page={MAX_OPEN_PRS}", hdrs,
                  timeout=HTTP_TIMEOUT, source="github")
    out = []
    for p in prs:
        if p.get("number") == pr:
            continue
        theirs = {f["filename"] for f in request(
            f"{base}/pulls/{p['number']}/files?per_page=100", hdrs,
            timeout=HTTP_TIMEOUT, source="github")}
        common = sorted(files & theirs)
        if common:
            out.append({"number": p["number"], "title": p.get("title", ""),
                        "branch": p.get("head", {}).get("ref", ""), "files": common})
    return out


def brain_memory(url: str, key: str, query: str) -> list[dict[str, str]]:
    resp = request(f"{url.rstrip('/')}/instances/{BRAIN_INSTANCE}/search",
                   {"X-API-Key": key, "Authorization": f"Bearer {key}"},
                   body={"query": query, "limit": MAX_MEMORY * 2},
                   timeout=HTTP_TIMEOUT, source="brain")
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


# ── contract findings (inline determinista, sin depender del modelo) ───────


FINDING_MARK = "<!--contrato:{cid}-->"  # la lectura del marcador vive en review-distribute.py


def _value_repr(value: object) -> str:
    """El value en el comentario: una línea, sin acentos de markdown que rompan el `code`,
    acotado (un value de contrato es corto; si no lo es, el YAML está como puede estar)."""
    text = " ".join(str(value if value is not None else "").split()).replace("`", "'")
    return text[:120] + "…" if len(text) > 120 else text


def finding_body(t: dict[str, Any], consumers: list[str]) -> str:
    cons = ", ".join(consumers) if consumers else "el registry no lista consumidores"
    return (FINDING_MARK.format(cid=t["id"]) + "\n"
            f"**Severidad alta · contrato `{t['id']}`**: el `value` de una entrada activa no muta. "
            f"Cambiado `{_value_repr(t.get('old_value'))}` → `{_value_repr(t.get('value'))}`. Consumidores: {cons}. "
            "Regla de la casa: un cambio incompatible es una entrada nueva `.vN+1` y la vieja pasa "
            "a `deprecated` (nunca se borra): restaura el value y añade la entrada nueva, o el "
            "bloque `exception` si procede. Lo publica el CI, no un modelo.")


def build_findings(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Valor mutado in situ, sin trailer `Contract-Change` del id y sin bloque exception.

    Las mismas condiciones que `[artifacts].artifact_instructions` piden al modelo: aquí se
    deciden de forma determinista sobre los hechos ya calculados. Sin línea en head no hay
    ancla inline: el hecho sigue en context.md para la tabla de la review."""
    trailer_ids = {cid for _, _, cid, _, _ in ctx["trailers"]}
    out = []
    for t in ctx["touched"]:
        if not any(f.startswith("value cambió") for f in t["facts"]):
            continue
        if any("bloque exception" in f for f in t["facts"]) or t["id"] in trailer_ids:
            continue
        if not str(t["line"]).isdigit():
            continue
        consumers = sorted({c for _, cons, _ in ctx["consumers"].get(t["id"], []) for c in cons})
        out.append({"id": t["id"], "file": t["file"], "line": int(t["line"]),
                    "old_value": t.get("old_value"), "value": t.get("value"),
                    "consumers": consumers, "body": finding_body(t, consumers)})
    return out


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
    findings_path = out.with_name("contract-findings.json")
    try:
        ctx = collect(args)
    except AuthError as exc:
        # No misleading partial context: only section 6 says what failed.
        empty = {"touched": [], "trailers": [], "consumers": {}, "prs": [], "memory": [],
                 "degraded": [(exc.source, f"{exc} — credencial rechazada")]}
        out.write_text(render(empty))
        findings_path.write_text("[]\n")  # sin contexto no hay hallazgo que publicar
        print(f"review-context: {exc}", file=sys.stderr)
        return 4
    out.write_text(render(ctx))
    findings = build_findings(ctx)
    findings_path.write_text(json.dumps(findings, ensure_ascii=False, indent=2) + "\n")
    print(f"review-context: {out} ({len(ctx['degraded'])} degradaciones, "
          f"{len(findings)} hallazgos de contrato inline)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
