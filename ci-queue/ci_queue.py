#!/usr/bin/env python3
"""Medición de la cola de CI de GitHub Actions — librería canónica (INFRA-400).

Cliente de la API, clasificación de labels y de cancelados, percentiles y carga
de pools. Consumidores:

  - `scripts/ci_queue_report.py` (CLI de informe y asserts, P1/P5)
  - `ci-queue/exporter.py` (exporter de métricas, P4)
  - auditoría de labels (P2) — usa `load_pools` y `classify_label`

Qué se mide (criterio C1): la espera de cada job es `started_at - created_at`
de la API de jobs; un job aún en cola (sin `started_at`) cuenta con su edad
hasta `now`; un job cancelado sin llegar a arrancar cuenta hasta su
`completed_at`. Los re-runs se miden por intento (`?attempt=N`): cada intento
es un evento real de cola.

Reutilización evaluada (50-entrega.md): `scripts/review_http.py` vive solo en
`main`, no en `deploy/prod`, y no trae paginación ni rate-limit; este cliente
es stdlib puro con las dos cosas.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"

# Runners self-hosted que no son scale set de ARC y por tanto no salen en
# infra/arc.yaml (decisión del architect en nota-architect-plan.md).
EXTRA_POOLS = ("x86-hermes",)

# Labels de GitHub-hosted (la granja de GitHub, no nuestra): no son «sin pool»,
# simplemente no pasan por ARC. macos-*/windows-* se documentan como fuera de
# pool (spec C2), no se migran.
_GITHUB_HOSTED_RE = re.compile(
    r"^(ubuntu-(latest|\d\d\.\d\d)(-\d+-core)?|macos-[\w.-]+|windows-[\w.-]+|self-hosted)$"
)
# …pero los larger runners (ubuntu/windows-N-core, blacksmith-*) sí los
# persigue el spec C2: si no hay license/runner detrás, el job espera horas.
_LARGER_RUNNER_RE = re.compile(
    r"^((ubuntu|windows)-(latest|\d\d\.\d\d)-\d+-core|blacksmith-.+)$"
)


def parse_iso(value: str | None) -> dt.datetime | None:
    """ISO-8601 de GitHub (`2026-10-01T20:05:58Z`) → datetime aware UTC."""
    if not value:
        return None
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def percentile(values: list[float], q: float) -> float:
    """Percentil por rango más cercano (n>=1); q en [0, 100]."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), -(-q * len(ordered) // 100)))  # ceil
    return float(ordered[rank - 1])


def load_pools(arc_yaml_text: str) -> frozenset[str]:
    """Pools válidos = `runnerScaleSetName` de infra/arc.yaml + EXTRA_POOLS.

    Fuente única (architect §2): el valor vive dentro del bloque `values: |` de
    cada Application, así que se lee el texto, no el YAML ya parseado.
    """
    pools = set(re.findall(r"^\s*runnerScaleSetName:\s*(\S+)\s*$", arc_yaml_text, re.M))
    return frozenset(pools | set(EXTRA_POOLS))


def classify_label(label: str, pools: frozenset[str]) -> str:
    """`pool` (ARC), `github` (granja GitHub) o `sin-pool` (ningún listener).

    Un label `sin-pool` es el caso C4: el job espera un runner que no existe.
    """
    if label in pools:
        return "pool"
    if _LARGER_RUNNER_RE.match(label):
        return "sin-pool"
    if _GITHUB_HOSTED_RE.match(label):
        return "github"
    return "sin-pool"


class GitHubError(Exception):
    """Fallo de la API que no es rate-limit: se propaga."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class RateLimited(Exception):
    """Cuota agotada; `retry_in` son segundos de espera según cabeceras."""

    def __init__(self, retry_in: float):
        super().__init__(f"rate limited, retry in {retry_in:.0f}s")
        self.retry_in = retry_in


def _default_token() -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    # sin token en el entorno: el del gh del host (nunca se imprime).
    return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True,
                          check=True).stdout.strip()


class Client:
    """GETs a api.github.com con paginación, ETag y respeto de X-RateLimit.

    `transport(url, headers) -> (status, headers, body)` es inyectable para
    tests; por defecto urllib con el token de `gh`/entorno. `sleep` inyectable
    para que los tests no esperen de verdad.
    """

    def __init__(self, token: str | None = None, transport=None, sleep=time.sleep,
                 base: str = API):
        self._token = token
        self._transport = transport or self._urllib_transport
        self._sleep = sleep
        self.base = base

    def _urllib_transport(self, url: str, headers: dict[str, str]):
        req = urllib.request.Request(url, headers=headers)  # noqa: S310
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    def get(self, path: str, params: dict | None = None,
            etag: str | None = None) -> tuple[object, dict, str | None]:
        """Una página: (json o None si 304, headers, etag). Espera si hay
        rate-limit (403/429 con cabeceras) y reintenta una vez; si sigue,
        RateLimited."""
        url = path if path.startswith("http") else self.base + path
        if params:
            url += "&" if "?" in url else "?"
            url += urllib.parse.urlencode(params)
        headers = {"Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28",
                   "Authorization": f"Bearer {self._token or _default_token()}"}
        if etag:
            headers["If-None-Match"] = etag
        for attempt in (0, 1, 2):
            try:
                status, hdrs, body = self._transport(url, headers)
            except OSError as exc:  # red transitoria (RemoteDisconnected, timeout)
                if attempt < 2:
                    self._sleep(2)
                    continue
                raise GitHubError(f"red: {type(exc).__name__} en {path}") from None
            if status == 304:
                return None, hdrs, etag
            if status in (403, 429) and attempt == 0:
                wait = _rate_wait(hdrs, self._now())
                if wait is not None:
                    self._sleep(wait)
                    continue
                raise GitHubError(f"HTTP {status} en {path} (permisos)", status)
            if status == 202:
                # Actions: datos aún migrando; se reintenta en el próximo ciclo.
                return {"_pending": True}, hdrs, hdrs.get("ETag")
            if status >= 400:
                raise GitHubError(f"HTTP {status} en {path}", status)
            return json.loads(body or b"{}"), hdrs, hdrs.get("ETag")
        raise RateLimited(_rate_wait(hdrs, self._now()) or 60)

    @staticmethod
    def _now() -> float:
        return time.time()

    def paginate(self, path: str, key: str, params: dict | None = None):
        """Items de `data[key]` a través de las páginas del cabecera Link."""
        params = dict(params or {})
        params.setdefault("per_page", 100)
        while True:
            data, hdrs, _etag = self.get(path, params)
            if isinstance(data, list):  # `/orgs/{org}/repos` responde un array
                yield from data
            elif not isinstance(data, dict) or data.get("_pending"):
                return
            else:
                yield from data.get(key, [])
            # La URL siguiente ya trae los params: se pide tal cual (absoluta).
            nxt = _next_link(hdrs)
            if not nxt:
                return
            path, params = nxt, None


def _next_link(headers: dict) -> str | None:
    for k, v in headers.items():
        if k.lower() == "link":
            for part in v.split(","):
                if 'rel="next"' in part:
                    return part[part.index("<") + 1:part.index(">")]
    return None


def _rate_wait(headers: dict, now: float) -> float | None:
    """Segundos a esperar según X-RateLimit-Reset o Retry-After; None si el 403
    no es de cuota (permisos)."""
    hdrs = {k.lower(): v for k, v in headers.items()}
    if hdrs.get("x-ratelimit-remaining") == "0":
        reset = float(hdrs.get("x-ratelimit-reset", now))
        return max(1.0, reset - now + 1)
    if "retry-after" in hdrs:
        return max(1.0, float(hdrs["retry-after"]))
    if hdrs.get("x-ratelimit-remaining") is not None:
        return None  # 403 con cuota disponible: no es rate-limit
    return 1.0  # sin cabeceras: reintento corto


class Job:
    """Un job medido. `wait` es la espera de cola en segundos."""

    __slots__ = ("repo", "run_id", "run_number", "attempt", "workflow", "event",
                 "branch", "name", "labels", "created_at", "started_at",
                 "completed_at", "status", "conclusion", "wait", "queued_now",
                 "synthetic", "prs")

    def __init__(self, repo, run_id, run_number, attempt, workflow, event, branch,
                 name, labels, created_at, started_at, completed_at, status,
                 conclusion, wait, queued_now, synthetic=False, prs=()):
        self.repo, self.run_id, self.run_number, self.attempt = repo, run_id, run_number, attempt
        self.workflow, self.event, self.branch, self.name = workflow, event, branch, name
        self.labels, self.created_at = labels, created_at
        self.started_at, self.completed_at = started_at, completed_at
        self.status, self.conclusion = status, conclusion
        self.wait, self.queued_now = wait, queued_now
        # True: medición a nivel de run (ahorra la llamada de jobs en runs
        # rápidos); no tiene labels y no participa en la clasificación.
        self.synthetic = synthetic
        self.prs = prs

    @property
    def label(self) -> str:
        return self.labels[0] if self.labels else "?"

    @property
    def never_ran(self) -> bool:
        """El job nunca llegó a un runner: sin `started_at`, o con el arranque
        fantasma de la API (`started_at == created_at` y luego muere sin éxito
        tras horas — el caso del job esperando un runner inexistente)."""
        if self.started_at is None:
            return self.status != "completed" or self.conclusion != "success"
        return (self.started_at == self.created_at
                and self.conclusion not in (None, "success")
                and self.completed_at is not None
                and (self.completed_at - self.created_at).total_seconds() > 60)

    @property
    def ref(self) -> str:
        pr = f" (PR {self.prs[0]})" if self.prs else ""
        return f"{self.repo}#{self.run_number}{pr}·{self.name}"


# Runs cuya espera a nivel de run está por debajo (segundos): se miden con
# `run_started_at` de la propia lista y NO se pide la API de jobs (la espera del
# job no puede superar a la del run más que en segundos; con ~6000 runs/semana
# en la org y 5000 llamadas/h de cuota, preguntar por cada run no cabe).
FAST_RUN_SECONDS = 30


def collect_jobs(client, org: str, since: dt.datetime, until: dt.datetime,
                 now: dt.datetime | None = None,
                 repos: list[str] | None = None) -> list[Job]:
    """Jobs de la org en [since, until]: runs por repo (no hay endpoint org de
    runs accesible sin admin) + runs en cola ahora mismo. Los runs lentos,
    cancelados, en cola o con re-runs se miden con la API de jobs por intento;
    los rápidos, con `run_started_at` (ver FAST_RUN_SECONDS)."""
    from concurrent.futures import ThreadPoolExecutor

    now = now or dt.datetime.now(dt.timezone.utc)
    if repos is None:
        repos = [r["name"] for r in client.paginate(f"/orgs/{org}/repos", "repositories")
                 if not r.get("archived")]

    def one_repo(repo: str) -> list[Job]:
        out: list[Job] = []
        seen: set[int] = set()
        for params in ({"created": f">={iso(since)}"}, {"status": "queued"}):
            for run in client.paginate(f"/repos/{org}/{repo}/actions/runs",
                                       "workflow_runs", dict(params)):
                if run["id"] in seen:
                    continue
                seen.add(run["id"])
                out.extend(_measure_run(client, org, repo, run, now))
        return out

    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = [j for part in pool.map(one_repo, sorted(repos)) for j in part]
    return [j for j in jobs if (j.created_at and since <= j.created_at <= now)
            or j.queued_now]


def _measure_run(client, org: str, repo: str, run: dict, now: dt.datetime) -> list[Job]:
    created = parse_iso(run.get("created_at"))
    started = parse_iso(run.get("run_started_at"))
    if created is None:
        return []
    interesting = (
        run.get("conclusion") == "cancelled"
        or run.get("status") != "completed"
        or int(run.get("run_attempt") or 1) > 1
        or (started is not None and (started - created).total_seconds() > FAST_RUN_SECONDS)
        or started is None  # queued/in_progress de verdad
    )
    if not interesting:
        return [Job(
            repo=repo, run_id=run["id"], run_number=run.get("run_number"),
            attempt=1, workflow=run.get("name"), event=run.get("event"),
            branch=run.get("head_branch"), name="(run)", labels=(),
            created_at=created, started_at=started,
            completed_at=parse_iso(run.get("updated_at")),
            status="completed", conclusion=run.get("conclusion"),
            wait=max(0.0, (started - created).total_seconds()),
            queued_now=False, synthetic=True,
            prs=tuple(pr["number"] for pr in run.get("pull_requests") or ()),
        )]
    return _run_jobs(client, org, repo, run, now)


def _run_jobs(client, org: str, repo: str, run: dict, now: dt.datetime) -> list[Job]:
    """Jobs del run (el último intento: la API de jobs por `attempt` devuelve
    los mismos timestamps para todos los intentos, no aporta nada y gasta
    cuota). `floor` es la espera a nivel de run — desde `created_at` hasta que
    el run arrancó de verdad — que la API de jobs oculta en runs en cola y con
    re-runs; cada job se mide al menos con ella."""
    created = parse_iso(run.get("created_at"))
    run_started = parse_iso(run.get("run_started_at"))
    if run.get("status") != "completed":
        floor = ((run_started or now) - created).total_seconds()  # en cola ya
    elif run_started and int(run.get("run_attempt") or 1) == 1:
        floor = (run_started - created).total_seconds()
    else:
        floor = None  # re-run: se calcula con el primer started_at abajo
    try:
        page = client.get(f"/repos/{org}/{repo}/actions/runs/{run['id']}/jobs",
                          {"per_page": 100})[0]
    except GitHubError:
        return []
    prs = tuple(pr["number"] for pr in run.get("pull_requests") or ())
    out = []
    for job in (page or {}).get("jobs", []):
        j_created = parse_iso(job.get("created_at"))
        started = parse_iso(job.get("started_at"))
        completed = parse_iso(job.get("completed_at"))
        if job.get("conclusion") == "skipped" or j_created is None:
            continue
        if started == j_created and job.get("conclusion") not in (None, "success") \
                and completed and (completed - j_created).total_seconds() > 60:
            end = completed  # arranque fantasma: esperó sin runner todo el rato
        else:
            end = started or completed or now
        wait = max(0.0, (end - j_created).total_seconds())
        out.append(Job(
            repo=repo, run_id=run["id"], run_number=run.get("run_number"),
            attempt=int(run.get("run_attempt") or 1), workflow=run.get("name"),
            event=run.get("event"), branch=run.get("head_branch"),
            name=job.get("name"), labels=tuple(job.get("labels") or ()),
            created_at=j_created, started_at=started, completed_at=completed,
            status=job.get("status"), conclusion=job.get("conclusion"),
            wait=wait, queued_now=job.get("status") != "completed", prs=prs,
        ))
    if floor is None and created:
        # Con re-runs, la cola real solo es recuperable si algún job del último
        # intento arrastra un `started_at` anterior al inicio de ese intento
        # (timestamp filtrado de un intento previo — también cuando `started`
        # es anterior al `created` del intento, visto en runs reales). Si no,
        # el hueco es tiempo entre re-ejecuciones manuales, no cola.
        starts = [j.started_at for j in out if j.started_at]
        if starts and (run_started is None or min(starts) < run_started):
            floor = (min(starts) - created).total_seconds()
        else:
            floor = 0.0
    if floor and floor > 0:
        for j in out:
            j.wait = max(j.wait, floor)
    return out


def classify_cancelled(job: Job, runs_index: dict[tuple[str, str, str], dt.datetime],
                       pools: frozenset[str] = frozenset()) -> str:
    """Causa de un job `cancelled` (regla escrita, spec C1):

    1. hay un run posterior del mismo repo+workflow+branch  → usuario:
       cancelación por concurrencia/empuje posterior;
    2. nunca llegó a un runner y llevaba >1 h con label sin pool
       → infra: el job esperaba un runner que no existe (timeout de cola);
    3. nunca llegó a arrancar                              → usuario: cancelado
       en cola a mano;
    4. arrancó y lo mataron en marcha                      → infra: runner o
       job caído (lo normal: el runner desaparece y el job se cancela).
    """
    key = (job.repo, job.workflow, job.branch)
    newer = runs_index.get(key)
    if newer and job.created_at and newer > job.created_at:
        return "usuario: reemplazado por push posterior (concurrencia)"
    if job.never_ran:
        if job.wait > 3600 and pools and \
                classify_label(job.label, pools) == "sin-pool":
            return "infra: esperando un runner inexistente (label sin pool)"
        return "usuario: cancelado en cola"
    return "infra: cancelado durante ejecución"


def runs_index(jobs: list[Job]) -> dict[tuple[str, str, str], dt.datetime]:
    """Último created_at por (repo, workflow, branch): base de la regla 1."""
    idx: dict[tuple[str, str, str], dt.datetime] = {}
    for j in jobs:
        key = (j.repo, j.workflow, j.branch)
        cur = idx.get(key)
        if j.created_at and (cur is None or j.created_at > cur):
            idx[key] = j.created_at
    return idx


def peak_concurrency(jobs: list[Job]) -> int:
    """Máximo de jobs en ejecución simultáneos (barrido de intervalos)."""
    events: list[tuple[dt.datetime, int]] = []
    for j in jobs:
        if j.started_at is None or j.never_ran:
            continue  # los jobs que nunca llegaron a un runner no ocupan plaza
        end = j.completed_at or j.created_at
        events.append((j.started_at, 1))
        events.append((end or j.started_at, -1))
    events.sort(key=lambda e: (e[0], -e[1]))
    peak = cur = 0
    for _, delta in events:
        cur += delta
        peak = max(peak, cur)
    return peak
