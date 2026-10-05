#!/usr/bin/env python3
"""Informe de la cola de CI de una org (INFRA-547, criterios C1 y C5).

CLI fino sobre `ci-queue/ci_queue.py`. Ejemplos:

  python3 scripts/ci_queue_report.py --org pocharlies-org --days 7 \
      --out docs/ci-queue-diagnosis-2026-10.md
  python3 scripts/ci_queue_report.py --org pocharlies-org \
      --since 2026-10-05T00:00:00Z --hours 48 --assert-p95 600 --assert-max 1800

Con `--since`/`--hours` o `--assert-*` la medición es exacta (API de jobs para
cada run); sin ellos, el diagnóstico de 7 días usa el atajo de `run_started_at`
para los runs rápidos (aproximación a la baja, declarada en `Conclusiones`).
La última línea de la salida es siempre `p95=<s> max=<s>` (segundos; con
`--assert-*` es lo único que se imprime, salvo el error por stderr) y el exit
es != 0 si algún assert se incumple. Sin servicios ni timers: es un cliente de
la API que se lanza a mano.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci-queue"))

import ci_queue as cq  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]


def build_report(jobs: list[cq.Job], pools: frozenset[str], since: dt.datetime,
                 until: dt.datetime, now: dt.datetime,
                 cases: list[tuple[str, int]] | None = None) -> str:
    measured = [j for j in jobs if not j.queued_now or j.wait > 0]
    waits = [j.wait for j in measured]
    p50, p95 = cq.percentile(waits, 50), cq.percentile(waits, 95)
    mx = max(waits, default=0.0)
    lines = [
        "# Diagnóstico de la cola de CI — pocharlies-org",
        "",
        f"Ventana: {cq.iso(since)} → {cq.iso(until)} (generado {cq.iso(now)}, "
        f"UTC). Fuente: API de jobs de GitHub Actions "
        f"(`created_at` vs `started_at`, re-runs por intento; un job aún en cola "
        f"cuenta con su edad hasta ahora). "
        f"Pools leídos de `infra/arc.yaml`: {', '.join(sorted(pools))}. "
        "Los runs rápidos (<30 s de espera a nivel de run) se miden con "
        "`run_started_at` de la lista de runs (fila `(run rápido)`); el resto, "
        "job a job con la API de jobs.",
        "",
        f"Jobs medidos: {len(measured)} · en cola ahora: "
        f"{sum(1 for j in jobs if j.queued_now)}",
        "",
        "## Espera por repo × label",
        "",
        "| repo | label | tipo | jobs | p50 | p95 | max |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]

    groups: dict[tuple[str, str], list[float]] = {}
    for j in measured:
        groups.setdefault((j.repo, "(run rápido)" if j.synthetic else j.label),
                          []).append(j.wait)
    rows = []
    for (repo, label), ws in groups.items():
        kind = ("run" if label == "(run rápido)"
                else cq.classify_label(label, pools))
        rows.append((cq.percentile(ws, 95), repo, label, len(ws),
                     cq.percentile(ws, 50), max(ws), kind))
    for p95_r, repo, label, n, p50_r, max_r, kind in sorted(rows, reverse=True):
        lines.append(f"| {repo} | {label} | {kind} | {n} | {p50_r:.0f} s | "
                     f"{p95_r:.0f} s | {max_r:.0f} s |")

    lines += ["", "## Peores esperas (top 10)", ""]
    for j in sorted(measured, key=lambda j: -j.wait)[:10]:
        lines.append(f"- {j.wait:.0f} s — `{j.ref}` · {j.label or '(run)'} "
                     f"· {j.created_at:%m-%d %H:%M} → "
                     f"{(j.started_at or now):%H:%M}")

    if cases:
        lines += ["", "## Casos citados en el spec", ""]
        for repo, number, *branch in cases:
            branch = branch[0] if branch else None
            hits = [j for j in jobs if j.repo == repo
                    and (j.run_number == number or number in j.prs
                         or (branch and j.branch == branch))]
            if hits:
                worst = max(hits, key=lambda j: j.wait)
                lines.append(f"- **{repo}#{number}**: {len(hits)} jobs, peor "
                             f"espera {worst.wait:.0f} s (`{worst.ref}`)")
            else:
                lines.append(f"- **{repo}#{number}**: sin jobs en la ventana.")

    sin_pool = [j for j in jobs if not j.synthetic
                and cq.classify_label(j.label, pools) == "sin-pool"]
    lines += ["", "## sin-pool (ningún listener ARC los sirve — caso C4)", ""]
    if sin_pool:
        lines += ["| repo | label | jobs | edad máx. |", "| --- | --- | --- | --- |"]
        by_label: dict[tuple[str, str], list[cq.Job]] = {}
        for j in sin_pool:
            by_label.setdefault((j.repo, j.label), []).append(j)
        for (repo, label), js in sorted(by_label.items(),
                                        key=lambda kv: -max(x.wait for x in kv[1])):
            lines.append(f"| {repo} | {label} | {len(js)} | "
                         f"{max(x.wait for x in js):.0f} s |")
    else:
        lines.append("Sin jobs con label sin pool en la ventana.")

    cancelled = [j for j in jobs if j.conclusion == "cancelled"]
    idx = cq.runs_index(jobs)
    lines += ["", "## cancelados (infra vs usuario, regla en `ci_queue.classify_cancelled`)", ""]
    if cancelled:
        causas: dict[str, list[cq.Job]] = {}
        for j in cancelled:
            causas.setdefault(cq.classify_cancelled(j, idx, pools), []).append(j)
        lines += ["| causa | jobs |", "| --- | --- |"]
        for causa, js in sorted(causas.items(), key=lambda kv: -len(kv[1])):
            lines.append(f"| {causa} | {len(js)} |")
        lines += ["", "Ejemplos (peor espera de cada causa):", ""]
        for causa, js in sorted(causas.items(), key=lambda kv: -len(kv[1])):
            worst = max(js, key=lambda j: j.wait)
            lines.append(f"- {causa} — `{worst.ref}`: {worst.wait:.0f} s")
    else:
        lines.append("Sin jobs cancelados en la ventana.")

    lines += ["", "## ocupación por hora (UTC)", "",
              "| hora | jobs iniciados | espera máx. | en cola al inicio |",
              "| --- | --- | --- | --- |"]
    hours = int((until - since).total_seconds() // 3600) + 1
    for h in range(hours):
        start = since + dt.timedelta(hours=h)
        end = start + dt.timedelta(hours=1)
        started = [j for j in measured if j.started_at and start <= j.started_at < end]
        waiting = [j for j in measured if j.created_at <= start
                   and (j.started_at or now) > start]
        lines.append(f"| {start:%m-%d %H} | {len(started)} | "
                     f"{max((j.wait for j in started), default=0.0):.0f} s | "
                     f"{len(waiting)} |")

    approx = any(j.synthetic for j in measured)
    peak = cq.peak_concurrency(measured)
    pool_jobs = [j for j in measured if not j.synthetic
                 and any(l in pools for l in j.labels)]
    peak_pool = cq.peak_concurrency(pool_jobs)
    pool_waits = [j.wait for j in pool_jobs]
    p95_pool, max_pool = cq.percentile(pool_waits, 95), max(pool_waits, default=0.0)
    worst_hour = max(range(hours),
                     key=lambda h: max((j.wait for j in measured
                                        if j.started_at
                                        and since + dt.timedelta(hours=h) <= j.started_at
                                        < since + dt.timedelta(hours=h + 1)), default=0))
    lines += [
        "", "## Conclusiones", "",
        f"- p50 = {p50:.0f} s · p95 = {p95:.0f} s · max = {mx:.0f} s "
        f"(jobs medidos: {len(measured)})",
        f"- Solo jobs de pool ARC (labels {', '.join(sorted(pools))}): "
        f"p95 = {p95_pool:.0f} s · max = {max_pool:.0f} s "
        f"(jobs: {len(pool_jobs)})",
        f"- Concurrencia máxima en ejecución: **{peak_pool}** en pool ARC · "
        f"{peak} en total (incluye GitHub-hosted).",
        f"- Hora con peor espera: {since + dt.timedelta(hours=worst_hour):%m-%d %H} UTC.",
        f"- Para P3 (maxRunners): pico ARC en ejecución = {peak_pool}; con el "
        f"p95 de pool ARC en {p95_pool:.0f} s, dimensionar ≥ {int(-(-peak_pool * 3 // 2)) if peak_pool else 'sin datos'} runners.",
        f"- Para P4 (N minutos de alerta): p95 de pool ARC = {p95_pool:.0f} s "
        f"≈ {p95_pool / 60:.1f} min; la espera máx. medida fue {mx:.0f} s.",
    ]
    if approx:
        lines += [
            "",
            "> Nota: las filas `(run rápido)` se midieron con `run_started_at` "
            "a nivel de run (atajo de cuota, no API de jobs): un job `needs` o "
            "de otro pool dentro de un run rápido no se ve. El p95 y el pico "
            "de concurrencia de este informe son un **suelo provisional**; la "
            "medida exacta (C5) se toma con `--since/--hours` o `--assert-*`, "
            "que usan la API de jobs para todos los runs.",
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None, client: cq.Client | None = None,
         now: dt.datetime | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--org", required=True)
    ap.add_argument("--days", type=float, default=None,
                    help="ventana terminando en ahora (por defecto 7)")
    ap.add_argument("--since", help="ISO; inicio explícito (con --hours)")
    ap.add_argument("--hours", type=float, help="duración desde --since")
    ap.add_argument("--out", help="escribe el informe markdown aquí")
    ap.add_argument("--assert-p95", type=float, metavar="S",
                    help="fallar (exit 2) si p95 > S segundos")
    ap.add_argument("--assert-max", type=float, metavar="S",
                    help="fallar (exit 2) si max > S segundos")
    ap.add_argument("--repo", action="append",
                    help="restringir a este repo (repetible); por defecto toda la org")
    ap.add_argument("--case", action="append", default=[], metavar="REPO#N",
                    help="añadir sección con el peor job de este run/PR (repetible)")
    args = ap.parse_args(argv)

    now = now or dt.datetime.now(dt.timezone.utc)
    if args.since:
        since = cq.parse_iso(args.since)
        until = since + dt.timedelta(hours=args.hours if args.hours else 24 * 7)
        until = min(until, now)
    else:
        until = now
        since = now - dt.timedelta(days=args.days or 7)

    exact = bool(args.since) or args.assert_p95 is not None \
        or args.assert_max is not None
    client = client or cq.Client()
    pools = cq.load_pools((REPO_ROOT / "infra" / "arc.yaml").read_text())
    jobs = cq.collect_jobs(client, args.org, since, until, now=now,
                            repos=args.repo, exact=exact)
    cases = []
    for c in args.case:
        repo, number = c.rsplit("#", 1)
        branch = None
        try:  # el API de runs trae pull_requests vacío: el PR se resuelve por rama
            branch = client.get(f"/repos/{args.org}/{repo}/pulls/{number}")[0]["head"]["ref"]
        except cq.GitHubError:
            pass
        cases.append((repo, int(number), branch))
    report = build_report(jobs, pools, since, until, now, cases=cases)
    # La línea de resultado es SIEMPRE lo último (y lo único con --assert-*):
    # C5 la lee sin ambigüedad.
    if args.out:
        Path(args.out).write_text(report)
    elif not (args.assert_p95 is not None or args.assert_max is not None):
        print(report)

    waits = [j.wait for j in jobs if not j.queued_now or j.wait > 0]
    p95, mx = cq.percentile(waits, 95), max(waits, default=0.0)
    print(f"p95={p95:.0f} max={mx:.0f}")
    failed = []
    if args.assert_p95 is not None and p95 > args.assert_p95:
        failed.append(f"p95 {p95:.0f} s > {args.assert_p95:.0f} s")
    if args.assert_max is not None and mx > args.assert_max:
        failed.append(f"max {mx:.0f} s > {args.assert_max:.0f} s")
    if failed:
        print("ASSERT FALLADO: " + "; ".join(failed), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
