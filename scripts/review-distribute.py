#!/usr/bin/env python3
"""Distribute one PR review (PR-Agent markdown) to its three consumers.

Writes, in this order and always (contract `pr_review.v1`, schemas/pr_review.v1.json):
  1 <out-dir>/payload.json  — even when PR-Agent failed (status degraded|skipped)
  2 push-ingest to the brain instance `local-ops` (adapter `pr_review`,
    source_id `pr_review:<owner>/<repo>#<pr>`); no BRAIN_CI_KEY or a brain that
    fails = degraded, exit 0
  3 GitHub labels `changes_required` / `possible security issue`, set or removed
    from the payload; no other label is ever touched
  4 <out-dir>/distribute.json — what each step did (state ok|sin_clave|degradado|
    rechazado|dry_run and the HTTP status); scripts/review-health.py counts it
  5 <out-dir>/notify.txt — plain text for humans. This script never calls
    Telegram: the existing `avisar` job sends the file.

With `--findings <contract-findings.json>` (written by scripts/review-context.py)
it also publishes each contract finding as an INLINE review comment through the
GitHub API (`pulls/{pr}/comments`, anchored to head_sha, path and the line of the
changed value), deterministically and without depending on the model. Each body
carries a `<!--contrato:<id>-->` marker: on a re-run the same finding is left
alone if it is identical on the current commit, and is deleted and re-posted when
the line, the text or the head commit changed. The step is recorded in
distribute.json as `inline_contract_findings`; it never blocks (degraded on 4xx/
5xx other than 401/403, which is exit 4 like every other GitHub step here).

Expected `--review-md` format (what INFRA-331 pins in PR-Agent `extra_instructions`).
The parser is line-based and tolerant; anything it does not recognise is kept in
`content` but yields no field (`unknown` / `false` / no finding):
  Merge recommendation: merge | changes_required | needs_human    (own line;
      also `Recomendación de merge:`; spaces or hyphens instead of `_` accepted)
  Security concerns: <text>          (own line; also `Possible security issue:`;
      a value starting with no / none / false / n/a / ninguno / sin = false,
      anything else = possible_security_issue true)
  One finding per list item (`-`, `*` or `1.`), file:line first, severity optional
  in square brackets before or after it, then the summary:
      - [high] `src/db.py:42` — string-concatenated query with user input
      - `scripts/run.sh:7` [low]: missing quote around variable
  Items without `path/file.ext:LINE` are not findings. At most 50 are kept.
  A missing --review-md file = status skipped; an empty one = status degraded.

It calls no model and has no dependencies beyond the standard library and its
sibling `scripts/review_http.py`.
Exit codes: 0 (also degraded), 2 invalid usage / missing mandatory env / invalid
contract-findings, 4 on 401/403 from any API. No other code. Tokens come from the
environment (GH_TOKEN, BRAIN_CI_KEY) and are never printed. Idempotent: it
overwrites, and an inline finding already in place is not re-posted.

Usage:
    review-distribute.py --repo o/r --pr 7 --head-sha <sha> --review-md review.md
    review-distribute.py --repo o/r --pr 7 --head-sha <sha> --findings .review/contract-findings.json
    review-distribute.py --dry-run --repo o/r --pr 7     # no network, fixture review
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))  # el módulo común vive junto a este script
from review_http import AuthError, Degraded, github_headers, request  # noqa: E402

SCHEMA_ID = "pr_review.v1"
SCHEMA_FILE = Path(__file__).resolve().parent.parent / "schemas/pr_review.v1.json"
DRYRUN_REVIEW = Path(__file__).resolve().parent.parent / "tests/fixtures/review-distribute/review.md"
DEFAULT_BRAIN_URL = "http://skirmshop-brain.skirmshop-brain-prod.svc.cluster.local"
BRAIN_INSTANCE = "local-ops"
ADAPTER = "pr_review"
LABEL_CHANGES = "changes_required"
LABEL_SECURITY = "possible security issue"
MAX_CONTENT = 12 * 1024  # bytes; the brain cuts at 16384 chars, the margin is on purpose
MAX_FINDINGS = 50
HTTP_TIMEOUT = 15
RECOMMENDATIONS = ("merge", "changes_required", "needs_human")

RECOMMENDATION_RE = re.compile(
    r"^\W*(?:merge[ _-]recommendation|recomendaci[oó]n(?: de merge)?)\W*:\s*\W*"
    r"(merge|changes[ _-]required|needs[ _-]human)\b", re.I | re.M)
SECURITY_RE = re.compile(
    r"^\W*(?:possible[ _]security[ _]issue|security concerns?)\W*:\s*(.+)$", re.I | re.M)
NEGATIVE_RE = re.compile(r"^\W*(?:no|none|false|n/a|ninguno|ninguna|sin)\b", re.I)
FINDING_RE = re.compile(
    r"^\s*(?:[-*]|\d+\.)\s*(?:\[(?P<sev>[A-Za-z]+)\]\s*)?`?(?P<file>[\w./@-]+\.\w+):(?P<line>\d+)`?"
    r"\s*(?:\[(?P<sev2>[A-Za-z]+)\])?\s*[—:–-]*\s*(?P<sum>.*\S)?\s*$", re.M)
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


# AuthError, Degraded y el cliente HTTP: scripts/review_http.py (una sola copia).

# ── payload ─────────────────────────────────────────────────────────────────


def truncate(text: str, limit: int = MAX_CONTENT) -> str:
    raw = text.encode()
    if len(raw) <= limit:
        return text
    note = "\n\n_[recortado a 12 KB]_"
    cut = raw[: limit - len(note.encode())].decode(errors="ignore")
    return cut + note


def parse_review(md: str) -> dict[str, Any]:
    m = RECOMMENDATION_RE.search(md)
    rec = re.sub(r"[ -]", "_", m.group(1).lower()) if m else "unknown"
    s = SECURITY_RE.search(md)
    security = bool(s) and not NEGATIVE_RE.match(s.group(1).strip())
    findings = []
    for f in FINDING_RE.finditer(md):
        findings.append({"file": f["file"], "line": int(f["line"]),
                         "severity": (f["sev"] or f["sev2"] or "info").lower(),
                         "summary": (f["sum"] or "").strip()[:300]})
        if len(findings) == MAX_FINDINGS:
            break
    return {"merge_recommendation": rec, "possible_security_issue": security, "findings": findings}


def build_payload(repo: str, pr: int, head_sha: str, review_md: Path | None) -> dict[str, Any]:
    if review_md is None or not review_md.is_file():
        status, md = "skipped", ""
    else:
        md = review_md.read_text(errors="replace")
        status = "ok" if md.strip() else "degraded"
    parsed = parse_review(md) if status == "ok" else {
        "merge_recommendation": "unknown", "possible_security_issue": False, "findings": []}
    if status != "ok":  # a dead review blocks nothing
        parsed["merge_recommendation"], parsed["possible_security_issue"] = "unknown", False
    return {
        "schema": SCHEMA_ID, "repo": repo, "pr": pr, "head_sha": head_sha, "status": status,
        "merge_recommendation": parsed["merge_recommendation"],
        "changes_required": parsed["merge_recommendation"] == "changes_required",
        "possible_security_issue": parsed["possible_security_issue"],
        "findings": parsed["findings"], "content": truncate(md),
    }


def validate(instance: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Just the JSON Schema keywords schemas/pr_review.v1.json uses (stdlib only)."""
    errs: list[str] = []
    if "const" in schema and instance != schema["const"]:
        errs.append(f"{path}: debe ser {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errs.append(f"{path}: {instance!r} fuera de {schema['enum']}")
    types = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int}
    t = schema.get("type")
    if t:
        ok = isinstance(instance, types[t]) and not (t == "integer" and isinstance(instance, bool))
        if not ok:
            return errs + [f"{path}: debe ser {t}"]
    if isinstance(instance, str):
        if len(instance) < schema.get("minLength", 0):
            errs.append(f"{path}: demasiado corto")
        if len(instance) > schema.get("maxLength", 1 << 60):
            errs.append(f"{path}: demasiado largo")
    if isinstance(instance, int) and not isinstance(instance, bool) and instance < schema.get("minimum", instance):
        errs.append(f"{path}: menor que {schema['minimum']}")
    if isinstance(instance, dict):
        props = schema.get("properties", {})
        errs += [f"{path}.{k}: obligatorio" for k in schema.get("required", []) if k not in instance]
        if schema.get("additionalProperties") is False:
            errs += [f"{path}.{k}: no permitido" for k in instance if k not in props]
        for k, sub in props.items():
            if k in instance:
                errs += validate(instance[k], sub, f"{path}.{k}")
    if isinstance(instance, list) and "items" in schema:
        for i, item in enumerate(instance):
            errs += validate(item, schema["items"], f"{path}[{i}]")
    return errs


def invariants(p: dict[str, Any]) -> list[str]:
    """Rules of INFRA-298 §6 that the JSON schema cannot say."""
    errs = []
    if p["changes_required"] != (p["merge_recommendation"] == "changes_required"):
        errs.append("changes_required debe ser (merge_recommendation == changes_required)")
    if p["status"] != "ok" and (p["changes_required"] or p["possible_security_issue"]
                                or p["merge_recommendation"] != "unknown"):
        errs.append("con status != ok no hay recomendación ni etiquetas (una review caída no bloquea nada)")
    return errs


def notify_text(p: dict[str, Any]) -> str:
    lines = [f"{p['repo']}#{p['pr']} · recomendación: {p['merge_recommendation']} · "
             f"{len(p['findings'])} hallazgos",
             f"https://github.com/{p['repo']}/pull/{p['pr']}"]
    if p["status"] != "ok":
        lines.insert(1, f"review {p['status']}: no bloquea nada")
    if p["possible_security_issue"]:
        lines.insert(1, "posible problema de seguridad")
    text = "\n".join(lines[:3])
    return ANSI_RE.sub("", re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", text)) + "\n"


# ── HTTP (cliente y clasificación de errores: scripts/review_http.py) ──────


def push_ingest(p: dict[str, Any], url: str, key: str) -> None:
    meta = {k: v for k, v in p.items() if k != "content"}  # contract fields, flat
    doc = {"source_id": f"{ADAPTER}:{p['repo']}#{p['pr']}", "content": p["content"], "metadata": meta}
    request(f"{url.rstrip('/')}/instances/{BRAIN_INSTANCE}/push-ingest",
            {"X-API-Key": key, "Authorization": f"Bearer {key}"}, method="POST",
            body={"adapter": ADAPTER, "documents": [doc]}, timeout=HTTP_TIMEOUT, source="brain")


def sync_labels(p: dict[str, Any], token: str) -> None:
    hdrs = github_headers(token)
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    base = f"{api}/repos/{p['repo']}/issues/{p['pr']}/labels"
    for label, on in ((LABEL_CHANGES, p["changes_required"]),
                      (LABEL_SECURITY, p["possible_security_issue"])):
        if on:
            request(base, hdrs, method="POST", body={"labels": [label]},
                    timeout=HTTP_TIMEOUT, source="github")
        else:
            request(f"{base}/{urllib.parse.quote(label)}", hdrs, method="DELETE",
                    ok404=True, timeout=HTTP_TIMEOUT, source="github")


# ── inline contract findings ────────────────────────────────────────────────

FINDING_MARK_RE = re.compile(r"<!--contrato:([a-z0-9][a-z0-9._-]*)-->")
COMMENTS_PAGES = 5  # 100 por página: los nuestros se buscan por su marcador


def load_findings(path: Path) -> list[dict[str, Any]]:
    """`.review/contract-findings.json` (scripts/review-context.py). Un fichero roto
    es un bug del CI, no una condición de runtime: sale 2 como payload inválido."""
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError("contract-findings.json debe ser una lista")
    for f in data:
        if not (isinstance(f, dict) and re.fullmatch(r"[a-z0-9][a-z0-9._-]*", str(f.get("id", "")))
                and f.get("file") and isinstance(f.get("line"), int) and f["line"] >= 1
                and f.get("body") and FINDING_MARK_RE.search(f["body"])):
            raise ValueError(f"hallazgo inválido: {str(f)[:120]}")
    return data


def post_inline_findings(p: dict[str, Any], findings: list[dict[str, Any]], token: str) -> str:
    """Publica cada hallazgo en su línea, anclado a head_sha. Repite solo lo que cambió.

    Devuelve un resumen para stdout. 401/403 sube AuthError (exit 4); el resto de 4xx/5xx,
    Degradado: un comentario que no salió no bloquea la distribución."""
    hdrs = github_headers(token)
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    repo, pr, head = p["repo"], p["pr"], p["head_sha"]
    list_base = f"{api}/repos/{repo}/pulls/{pr}/comments"
    existing: dict[str, list[dict[str, Any]]] = {}
    for page in range(1, COMMENTS_PAGES + 1):
        batch = request(f"{list_base}?per_page=100&page={page}", hdrs,
                        timeout=HTTP_TIMEOUT, source="github")
        for c in batch:
            # solo los nuestros (Bot): un humano que copie el marcador no se borra ni se toca
            if (c.get("user") or {}).get("type") != "Bot":
                continue
            m = FINDING_MARK_RE.search(c.get("body", ""))
            if m:
                existing.setdefault(m.group(1), []).append(c)
        if len(batch) < 100:
            break
    posted = skipped = 0
    for f in findings:
        # GET /pulls/{n}/comments trae commit_id/original_commit_id en el propio comentario
        # (pull_request_review_id es solo el id de la review); un push nuevo cambia el head
        # y el comentario viejo queda outdated: se borra y se republica anclado al nuevo.
        current = [c for c in existing.get(f["id"], [])
                   if c.get("path") == f["file"] and c.get("line") == f["line"]
                   and c.get("body") == f["body"] and c.get("commit_id") == head]
        if current:
            skipped += 1
            continue
        for c in existing.get(f["id"], []):  # el anterior (línea, texto o commit viejos)
            request(f"{api}/repos/{repo}/pulls/comments/{c['id']}", hdrs, method="DELETE",
                    ok404=True, timeout=HTTP_TIMEOUT, source="github")
        request(list_base, hdrs, method="POST", timeout=HTTP_TIMEOUT, source="github",
                body={"body": f["body"], "commit_id": head, "path": f["file"],
                      "line": f["line"], "side": "RIGHT"})
        posted += 1
    return f"{posted} publicado(s), {skipped} en su sitio"


# ── main ────────────────────────────────────────────────────────────────────


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", required=True, help="owner/repo")
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--head-sha", help="default: GITHUB_EVENT_PATH pull_request.head.sha")
    p.add_argument("--review-md", help="PR-Agent markdown output; absent or missing = status skipped")
    p.add_argument("--findings", help="contract-findings.json (review-context.py): each finding "
                                      "is posted as an inline review comment, deterministically")
    p.add_argument("--out-dir", default=".review")
    p.add_argument("--dry-run", action="store_true", help="no network: fixture review, files only")
    return p


def head_from_event() -> str | None:
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or not Path(path).is_file():
        return None
    return ((json.loads(Path(path).read_text()).get("pull_request") or {}).get("head") or {}).get("sha")


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2  # --help is fine; any other parse error is usage
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo) or args.pr < 1:
        print("review-distribute: --repo owner/repo y --pr >= 1", file=sys.stderr)
        return 2
    head = args.head_sha or head_from_event() or ("0" * 40 if args.dry_run else None)
    token = os.environ.get("GH_TOKEN", "")
    if not head or not (token or args.dry_run):
        print("review-distribute: faltan --head-sha (o GITHUB_EVENT_PATH) y GH_TOKEN", file=sys.stderr)
        return 2
    review = Path(args.review_md) if args.review_md else (DRYRUN_REVIEW if args.dry_run else None)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = build_payload(args.repo, args.pr, head, review)
    errors = validate(payload, json.loads(SCHEMA_FILE.read_text())) + invariants(payload)
    if errors:  # a bug here, not a runtime condition
        print("review-distribute: payload inválido: " + "; ".join(errors), file=sys.stderr)
        return 2
    (out / "payload.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    steps: list[str] = []
    record: dict[str, Any] = {}  # .review/distribute.json: what review-health.py counts
    rc = 0
    # Two independent steps: labels are the primary channel to pr-watcher, so a
    # 401 from the brain must not skip them (and a 403 from GitHub must not skip
    # the push-ingest). Exit 4 if either one is rejected.
    key = os.environ.get("BRAIN_CI_KEY", "")
    if args.dry_run:
        steps.append("push-ingest: omitido (--dry-run)")
        record["push_ingest"] = {"state": "dry_run", "http": None}
    elif not key:
        steps.append("push-ingest: omitido, degradado (sin BRAIN_CI_KEY)")
        record["push_ingest"] = {"state": "sin_clave", "http": None}
    else:
        try:
            push_ingest(payload, os.environ.get("BRAIN_URL", DEFAULT_BRAIN_URL), key)
            steps.append("push-ingest: ok")
            record["push_ingest"] = {"state": "ok", "http": None}
        except Degraded as exc:
            steps.append(f"push-ingest: degradado ({exc})")
            record["push_ingest"] = {"state": "degradado", "http": exc.code}
        except AuthError as exc:
            steps.append(f"push-ingest: error: {exc} — credencial rechazada")
            record["push_ingest"] = {"state": "rechazado", "http": exc.code}
            rc = 4
    if args.dry_run:
        steps.append(f"etiquetas: omitidas (--dry-run); {LABEL_CHANGES}={payload['changes_required']}, "
                     f"{LABEL_SECURITY}={payload['possible_security_issue']}")
        record["labels"] = {"state": "dry_run", "http": None}
    else:
        try:
            sync_labels(payload, token)
            steps.append("etiquetas: ok")
            record["labels"] = {"state": "ok", "http": None}
        except Degraded as exc:
            steps.append(f"etiquetas: degradado ({exc})")
            record["labels"] = {"state": "degradado", "http": exc.code}
        except AuthError as exc:
            steps.append(f"etiquetas: error: {exc} — credencial rechazada")
            record["labels"] = {"state": "rechazado", "http": exc.code}
            rc = 4
    # Hallazgos de contrato en línea: deterministas, los calculó review-context.py antes
    # de PR-Agent. Se publican también con la review caída (status != ok): el hallazgo
    # depende del diff, no del modelo.
    findings_path = Path(args.findings) if args.findings else None
    if findings_path and findings_path.is_file():
        try:
            findings = load_findings(findings_path)
        except (ValueError, OSError) as exc:  # bug del artefacto del CI, no condición de runtime
            print(f"review-distribute: contract-findings inválido: {exc}", file=sys.stderr)
            return 2
        if not findings:
            record["inline_contract_findings"] = {"state": "sin_hallazgos", "http": None}
        elif args.dry_run:
            steps.append(f"hallazgos inline: omitidos (--dry-run); {len(findings)} en "
                         f"{findings_path.name}")
            record["inline_contract_findings"] = {"state": "dry_run", "http": None,
                                                  "posted": len(findings)}
        else:
            try:
                resumen = post_inline_findings(payload, findings, token)
                steps.append(f"hallazgos inline: ok ({resumen})")
                record["inline_contract_findings"] = {"state": "ok", "http": None}
            except Degraded as exc:
                steps.append(f"hallazgos inline: degradado ({exc})")
                record["inline_contract_findings"] = {"state": "degradado", "http": exc.code}
            except AuthError as exc:
                steps.append(f"hallazgos inline: error: {exc} — credencial rechazada")
                record["inline_contract_findings"] = {"state": "rechazado", "http": exc.code}
                rc = 4
    (out / "distribute.json").write_text(json.dumps(record, indent=2) + "\n")
    (out / "notify.txt").write_text(notify_text(payload))  # also on exit 4: humans must see it
    print(f"review-distribute: status={payload['status']} recomendación={payload['merge_recommendation']} "
          f"hallazgos={len(payload['findings'])}")
    for s in steps:
        print(f"review-distribute: {s}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
