#!/usr/bin/env python3
"""ci-queue-exporter — métricas Prometheus de la cola de CI por label (INFRA-550).

Reutiliza `ci_queue.py` (cliente, clasificador, pools): no hay aquí ni segundo
cliente ni lista de pools propia. Emite solo agregados:

  ci_queue_queued_jobs{label,pool}                       jobs en cola ahora
  ci_queue_oldest_queued_job_age_seconds{label,pool,repo}  (repo solo con cola >0)
  ci_queue_scrape_success_timestamp_seconds              ceguera propia
  ci_queue_api_rate_remaining                            cuota GitHub restante
  ci_queue_errors_total                                  scrapes parciales con fallo

Un scrape cada 5 min: repos de la org con actividad en 7 días → runs con
`status=queued` por repo (ETag: los 304 no gastan cuota) → jobs de esos runs.
Los jobs con label sin pool nunca llegan al listener ARC, por eso la fuente es
la API de GitHub (decisión del architect, nota-architect-plan.md §1B).

Auth: token de instalación de la GitHub App `arc-github-app` montado como
Secret — lo genera external-secrets con el generator GithubAccessToken (ver
kustomization.yaml); sin PAT. La validez del token (1 h) la gestiona ESO, no
aquí: el fichero se relee en cada request.

La API nunca es de fiar: respuestas con campos ausentes o repos que fallan
suman a `ci_queue_errors_total` y no matan el scrape.

Límite conocido (plan del architect §1B): `status=queued` solo lista runs SIN
ningún job arrancado. Un job con label sin pool dentro de un run cuyos otros
jobs ya corren es invisible para este exporter (y para la prueba de disparo de
un run de un solo job, que sí lo ve). El discriminador de «en cola» de cada job
es su `status`, no `started_at`: la API rellena `started_at == created_at` en
jobs que nunca tuvieron runner (`ci_queue.Job.never_ran`).
"""
from __future__ import annotations

import datetime as dt
import http.server
import os
import sys
import threading
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ci_queue  # noqa: E402

ORG = os.environ.get("CI_QUEUE_ORG", "pocharlies-org")
TOKEN_FILE = os.environ.get("CI_QUEUE_TOKEN_FILE", "/etc/ci-queue-token/token")
POOLS_FILE = os.environ.get("CI_QUEUE_POOLS_FILE",
                            os.path.join(os.path.dirname(os.path.abspath(__file__)), "pools.txt"))
INTERVAL = float(os.environ.get("CI_QUEUE_INTERVAL", "300"))
ACTIVE_DAYS = 7
PORT = int(os.environ.get("CI_QUEUE_PORT", "8080"))


def _token(path: str = TOKEN_FILE) -> str:
    with open(path) as f:
        return f.read().strip()


def _http(url: str, headers: dict):
    req = urllib.request.Request(url, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def make_transport(token_path: str = TOKEN_FILE, stats: dict | None = None, http=_http):
    """`http` con el token del fichero en cada request; deja en `stats` el
    X-RateLimit-Remaining de la última respuesta (también en 304)."""
    def transport(url: str, headers: dict):
        headers["Authorization"] = f"Bearer {_token(token_path)}"
        status, hdrs, body = http(url, headers)
        if stats is not None:
            rem = {k.lower(): v for k, v in hdrs.items()}.get("x-ratelimit-remaining")
            if rem is not None:
                stats["rate_remaining"] = int(rem)
        return status, hdrs, body
    return transport


def active_repos(client, org: str, now: dt.datetime,
                 days: int = ACTIVE_DAYS) -> list[str]:
    """Repos no archivados con push en los últimos `days` días (1 página: la
    org tiene ~60; si pasara de 100, paginate lo cubre igual)."""
    return sorted(
        r["name"] for r in client.paginate(f"/orgs/{org}/repos", "repositories")
        if r.get("name") and not r.get("archived")
        and (pushed := ci_queue.parse_iso(r.get("pushed_at"))) is not None
        and pushed >= now - dt.timedelta(days=days))


def scrape(client, pools, cache: dict, now: dt.datetime,
           org: str = ORG) -> dict:
    """Un ciclo: devuelve {queued: {(label,pool): n}, oldest: {(label,pool,repo): s},
    errors: n}. `cache` guarda (etag, runs) por repo: un 304 reutiliza la lista
    anterior sin gastar cuota. Los fallos por repo se anotan y siguen."""
    errors = 0
    queued: dict[tuple[str, str], int] = {}
    oldest: dict[tuple[str, str, str], float] = {}
    for repo in active_repos(client, org, now):
        try:
            etag, runs = cache.get(repo, (None, []))
            data, _hdrs, etag = client.get(f"/repos/{org}/{repo}/actions/runs",
                                           {"status": "queued", "per_page": 100},
                                           etag=etag)
            if data is None:  # 304: sin cambios desde el ciclo anterior
                runs = cache[repo][1]
            else:
                runs = data.get("workflow_runs", [])
            cache[repo] = (etag, runs)
            for run in runs:
                jobs = client.get(
                    f"/repos/{org}/{repo}/actions/runs/{run['id']}/jobs",
                    {"per_page": 100})[0]
                for job in (jobs or {}).get("jobs", []):
                    if job.get("status") != "queued":
                        continue  # in_progress/completed/waiting: no es cola de runners
                    created = ci_queue.parse_iso(job.get("created_at"))
                    if created is None:
                        errors += 1  # respuesta rara: se anota, no se muere el ciclo
                        continue
                    label = (job.get("labels") or ["?"])[0]
                    pool = ci_queue.classify_label(label, pools)
                    key = (label, pool)
                    queued[key] = queued.get(key, 0) + 1
                    age = max(0.0, (now - created).total_seconds())
                    k3 = (label, pool, repo)
                    oldest[k3] = max(oldest.get(k3, 0.0), age)
        except (ci_queue.GitHubError, ci_queue.RateLimited, OSError,
                KeyError, TypeError, ValueError, AttributeError):  # respuesta con forma rara
            errors += 1
    return {"queued": queued, "oldest": oldest, "errors": errors}


def _esc(v: str) -> str:
    """Valor de label del texto de exposición: `label` sale del `runs-on` de un
    workflow que cualquier miembro edita en una PR; una comilla, una barra o un
    salto de línea rompería la línea o inyectaría una serie falsa."""
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render(scrape_result: dict, ts_success: float, rate_remaining: int,
           errors_total: int) -> str:
    """`errors_total` incluye ya los de este ciclo."""
    out = [
        "# HELP ci_queue_queued_jobs jobs de GitHub Actions en cola ahora por label y clasificacion de pool",
        "# TYPE ci_queue_queued_jobs gauge",
    ]
    for (label, pool), n in sorted(scrape_result["queued"].items()):
        out.append(f'ci_queue_queued_jobs{{label="{_esc(label)}",pool="{_esc(pool)}"}} {n}')
    out += ["# HELP ci_queue_oldest_queued_job_age_seconds edad del job mas viejo en cola (desde created_at)",
            "# TYPE ci_queue_oldest_queued_job_age_seconds gauge"]
    for (label, pool, repo), s in sorted(scrape_result["oldest"].items()):
        out.append(f'ci_queue_oldest_queued_job_age_seconds{{label="{_esc(label)}",'
                   f'pool="{_esc(pool)}",repo="{_esc(repo)}"}} {s:.0f}')
    out += [
        "# HELP ci_queue_scrape_success_timestamp_seconds epoch del ultimo scrape completo (0 = ninguno)",
        "# TYPE ci_queue_scrape_success_timestamp_seconds gauge",
        f"ci_queue_scrape_success_timestamp_seconds {ts_success:.0f}",
        "# HELP ci_queue_api_rate_remaining X-RateLimit-Remaining visto en el ultimo request",
        "# TYPE ci_queue_api_rate_remaining gauge",
        f"ci_queue_api_rate_remaining {rate_remaining}",
        "# HELP ci_queue_errors_total fallos parciales acumulados de scrape",
        "# TYPE ci_queue_errors_total counter",
        f"ci_queue_errors_total {errors_total}",
    ]
    return "\n".join(out) + "\n"


class Server(http.server.ThreadingHTTPServer):
    metrics = "# HELP ci_queue_up 0\n"  # renderizable antes del primer scrape


class Handler(http.server.BaseHTTPRequestHandler):  # pragma: no cover - servidor
    def do_GET(self):
        if self.path.split("?")[0] not in ("/metrics", "/healthz"):
            self.send_error(404)
            return
        body = Server.metrics.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def run_cycle(client, pools, cache: dict, state: dict, now: dt.datetime) -> str:
    """Un ciclo completo → texto de exposición. `state` = {rate_remaining,
    ts_success, errors_total}: es el mismo dict que `make_transport(stats=…)`
    rellena con X-RateLimit-Remaining. `ts_success` solo avanza con 0 errores:
    un repo que falle siempre deja `CIQueueExporterBlind` disparado (fallar con
    ruido es intencionado, ver nota del architect)."""
    result = scrape(client, pools, cache, now)
    state["errors_total"] += result["errors"]
    if result["errors"] == 0:
        state["ts_success"] = now.timestamp()
    return render(result, state["ts_success"], state["rate_remaining"], state["errors_total"])


def loop(client, pools, stop: threading.Event, state: dict) -> None:  # pragma: no cover - servidor
    cache: dict = {}
    while not stop.is_set():
        try:
            Server.metrics = run_cycle(client, pools, cache, state,
                                       dt.datetime.now(dt.timezone.utc))
        except Exception as exc:  # noqa: BLE001 - el hilo no puede morir
            state["errors_total"] += 1
            print(f"scrape fallido: {type(exc).__name__}: {exc}", file=sys.stderr)
        stop.wait(INTERVAL)


def main() -> int:  # pragma: no cover - servidor
    with open(POOLS_FILE) as f:
        pools = ci_queue.load_pools(f.read())
    state = {"rate_remaining": 0, "ts_success": 0.0, "errors_total": 0}
    client = ci_queue.Client(token="montado",  # el transport pone el del fichero
                             transport=make_transport(stats=state))
    stop = threading.Event()
    threading.Thread(target=loop, args=(client, pools, stop, state), daemon=True).start()
    Server(("0.0.0.0", PORT), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
