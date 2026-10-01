#!/usr/bin/env python3
"""Nightly health signal of the PR review (INFRA-333 P5b): how often did the review NOT happen?

For one repo it reads the last 50 completed runs of the `PR review` workflow and,
from the artifact `pr-review-<pr>-<attempt>` each one uploads, decides per run:

  omitido  the review did not reach the PR or its distribution failed. Any of:
           - no artifact within retention (the run left no verdict)
           - payload.json `status` is not `ok` (PR-Agent skipped/degraded)
           - distribute.json: push-ingest or labels `degradado` (brain/GitHub answered
             4xx/5xx or was down) or `rechazado` (401/403)
  ok       anything else. `push_ingest: sin_clave` (BRAIN_CI_KEY not distributed yet,
           SC-1400) is NOT an omission: it is reported apart as a dependency.
  ajeno    the run did not execute the PR-Agent engine (`engine: propio`, a fork, a skipped
           job) or predates --since: it says nothing about this review. Left out of the ratio.
  expirado the run is older than the artifact retention (14 d): no data, left out of
           both sides of the ratio (it is neither omitted nor ok).

Red (exit 3) when the omission ratio is > 20 % (strictly: 10 of 50 is green, 11 of 50
is red; with fewer than 50 measurable runs the ratio is over the runs there are) or
when the latest measurable run concluded `failure` (a 401/403: broken credential).
No measurable runs = green with a note (nothing to judge).

Exit codes: 0 green, 2 invalid usage, 3 red, 4 GitHub answered 401/403 to this script.
GH_TOKEN comes from the environment and is never printed. No model calls. stdlib only.
The HTTP client and the AuthError/Degraded rule are shared with the rest of the review
pipeline in `scripts/review_http.py` (seguimiento D del arquitecto, INFRA-332/333).

Usage:
    review-health.py --repo pocharlies-org/k8s-litellm-pocharlies [--out .review-health/x.md]
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))  # el módulo común vive junto a este script
from review_http import AuthError, Degraded, github_headers, request  # noqa: E402

WORKFLOW_FILE = "pr-review.yml"
WINDOW = 50
THRESHOLD = 0.20
RETENTION_DAYS = 14  # keep equal to retention-days of "Upload the review record"
HTTP_TIMEOUT = 30
MEASURED = ("success", "failure")  # cancelled/skipped/neutral runs say nothing about the review


def api(url: str, token: str, raw: bool = False) -> Any:
    """GET de la API de GitHub (o el zip de un artefacto con raw=True)."""
    return request(url, github_headers(token), raw=raw, timeout=HTTP_TIMEOUT, source="GitHub")


def engine_ran(jobs: list[dict[str, Any]]) -> bool:
    """True when the PR-Agent job of the reusable workflow actually executed."""
    return any("PR-Agent" in j.get("name", "") and j.get("conclusion") not in (None, "skipped")
               for j in jobs)


def select_runs(runs: list[dict[str, Any]], jobs: dict[int, list[dict[str, Any]]],
                since: datetime | None, window: int = WINDOW) -> tuple[list[dict[str, Any]], int]:
    """Newest-first runs worth measuring + how many were `ajeno`. Window is cut AFTER filtering."""
    picked, foreign = [], 0
    for r in runs:
        if r.get("conclusion") not in MEASURED:
            continue
        created = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
        if (since and created < since) or not engine_ran(jobs.get(r["id"], [])):
            foreign += 1
            continue
        picked.append(r)
    return picked[:window], foreign


def classify(files: dict[str, Any] | None) -> tuple[str, list[str], bool]:
    """(`ok`|`omitido`, reasons, no_key) for the files of one artifact (None = no artifact)."""
    if files is None:
        return "omitido", ["sin artefacto: la review no dejó veredicto"], False
    reasons: list[str] = []
    payload = files.get("payload.json")
    if not isinstance(payload, dict):
        reasons.append("sin payload.json")
    elif payload.get("status") != "ok":
        reasons.append(f"review {payload.get('status')}")
    dist = files.get("distribute.json") or {}
    no_key = False
    for step, label in (("push_ingest", "push-ingest al brain"), ("labels", "etiquetas")):
        info = dist.get(step) or {}
        state = info.get("state")
        if state in ("degradado", "rechazado"):
            http = f" HTTP {info['http']}" if info.get("http") else ""
            reasons.append(f"{label} {state}{http}")
        if step == "push_ingest" and state == "sin_clave":
            no_key = True
    return ("omitido" if reasons else "ok"), reasons, no_key


def read_artifact(repo: str, run_id: int, token: str, base: str) -> dict[str, Any] | None:
    arts = api(f"{base}/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100", token)
    cand = [a for a in arts.get("artifacts", [])
            if re.fullmatch(r"pr-review-\d+-\d+", a.get("name", "")) and not a.get("expired")]
    if not cand:
        return None
    best = max(cand, key=lambda a: int(a["name"].rsplit("-", 1)[1]))  # last attempt wins
    data = api(f"{base}/repos/{repo}/actions/artifacts/{best['id']}/zip", token, raw=True)
    files: dict[str, Any] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in ("payload.json", "distribute.json"):
            for member in z.namelist():
                if member.rsplit("/", 1)[-1] == name:
                    try:
                        files[name] = json.loads(z.read(member))
                    except ValueError:
                        files[name] = None
    return files


def evaluate(runs: list[dict[str, Any]], artifacts: dict[int, dict[str, Any] | None],
             now: datetime, window: int = WINDOW, threshold: float = THRESHOLD,
             retention_days: int = RETENTION_DAYS, foreign: int = 0) -> dict[str, Any]:
    """Pure rule. `runs` newest first; `artifacts` run id -> files (None = none found)."""
    considered = [r for r in runs if r.get("conclusion") in MEASURED][:window]
    cutoff = now - timedelta(days=retention_days)
    omitted, ok, expired, no_key, rows = 0, 0, 0, 0, []
    for r in considered:
        created = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
        files = artifacts.get(r["id"])
        if files is None and created < cutoff:
            expired += 1
            continue
        verdict, reasons, nk = classify(files)
        no_key += nk
        omitted += verdict == "omitido"
        ok += verdict == "ok"
        if verdict == "omitido":
            rows.append((r["id"], r.get("html_url", ""), reasons))
    measured = omitted + ok
    ratio = omitted / measured if measured else 0.0
    latest_failed = bool(considered) and considered[0]["conclusion"] == "failure"
    red = []
    if ratio > threshold:
        red.append(f"omitidos {omitted}/{measured} ({ratio:.0%}) > {threshold:.0%}")
    if latest_failed:
        red.append("el último run concluyó en failure (credencial rota 401/403)")
    return {"considered": len(considered), "measured": measured, "omitted": omitted, "ok": ok,
            "expired": expired, "foreign": foreign, "no_key": no_key, "ratio": ratio, "red": red, "rows": rows}


def render(repo: str, ev: dict[str, Any]) -> str:
    verdict = "ROJO" if ev["red"] else "VERDE"
    lines = [f"### Salud de la review · {repo} · {verdict}", "",
             f"- runs considerados: {ev['considered']} · medidos: {ev['measured']} · "
             f"omitidos: {ev['omitted']} ({ev['ratio']:.0%}) · expirados (sin datos): {ev['expired']} · "
             f"ajenos (sin motor PR-Agent o previos a --since): {ev['foreign']}"]
    if ev["no_key"]:
        lines.append(f"- {ev['no_key']} run(s) sin BRAIN_CI_KEY: el payload no llega al brain "
                     "(dependencia SC-1400/B1, no se cuenta como omisión)")
    if not ev["measured"]:
        lines.append("- sin runs medibles: nada que juzgar")
    lines += [f"- ROJO: {r}" for r in ev["red"]]
    for run_id, url, reasons in ev["rows"][:10]:
        lines.append(f"  - run {run_id} {url}: {'; '.join(reasons)}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", required=True, help="owner/repo to measure")
    p.add_argument("--workflow", default=WORKFLOW_FILE)
    p.add_argument("--window", type=int, default=WINDOW)
    p.add_argument("--since", help="ISO date: ignore runs before it (e.g. before the artifact upload worked)")
    p.add_argument("--out", help="write the markdown report here too")
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2
    try:
        if args.since:
            datetime.fromisoformat(args.since.replace("Z", "+00:00"))
    except ValueError:
        print("review-health: --since debe ser una fecha ISO", file=sys.stderr)
        return 2
    token = os.environ.get("GH_TOKEN", "")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo) or args.window < 1 or not token:
        print("review-health: --repo owner/repo, --window >= 1 y GH_TOKEN", file=sys.stderr)
        return 2
    base = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    try:
        # over-fetch: cancelled/skipped runs are dropped before the window is cut
        runs = api(f"{base}/repos/{args.repo}/actions/workflows/{args.workflow}/runs"
                   f"?status=completed&per_page=100", token).get("workflow_runs", [])
        now = datetime.now(timezone.utc)
        since = datetime.fromisoformat(args.since.replace("Z", "+00:00")) if args.since else None
        if since and since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        jobs = {r["id"]: api(f"{base}/repos/{args.repo}/actions/runs/{r['id']}/jobs?per_page=30",
                             token).get("jobs", []) for r in runs if r.get("conclusion") in MEASURED
                and not (since and datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) < since)}
        measured, foreign = select_runs(runs, jobs, since, args.window)
        cutoff = now - timedelta(days=RETENTION_DAYS)
        arts = {r["id"]: read_artifact(args.repo, r["id"], token, base) for r in measured
                if datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) >= cutoff}
        ev = evaluate(measured, arts, now, window=args.window, foreign=foreign)
    except AuthError as exc:
        print(f"review-health: {exc} — credencial rechazada", file=sys.stderr)
        return 4
    except Degraded as exc:
        # The signal itself is down: that is not "green". Report and fail loudly.
        print(f"review-health: no se pudo medir ({exc})", file=sys.stderr)
        return 3
    text = render(args.repo, ev)
    print(text, end="")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text)
    return 3 if ev["red"] else 0


if __name__ == "__main__":
    sys.exit(main())
