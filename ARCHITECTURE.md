# ARCHITECTURE.md — k8s-gitops-pocharlies

> El orquestador **app-of-apps** de ArgoCD del cluster y la casa de los workflows reutilizables de CI/CD de la
> compañía. Es la raíz del despliegue: un error aquí afecta a todo el cluster. Escrito por `architect` (SC-1426).

## 1. Clientes y versiones

| cliente | repositorio / ruta | versión desplegada | cómo se despliega |
|---|---|---|---|
| App-of-apps `root` | `kustomization.yaml` raíz → `infra/*.yaml`, `apps/*.yaml`, `legacy/*.yaml`, `bootstrap/app-of-apps.yaml` | `origin/deploy/prod` = f2a8ce0 | ArgoCD app `root` (path `.`, `deploy/prod`) |
| Workflows reutilizables | `.github/workflows/reusable-{ci,release,manifest-release,deploy-stg,pr-review}.yml` | se consumen como `@main` o por SHA (`@ac96743b…`) | cada repo `k8s-*` los llama |

Un solo «cliente»: ArgoCD.

## 2. Dependencias, en ambos sentidos

- **Depende de** — cada repo `k8s-*` y `dgx-infra` (cada `Application` apunta a su repo/rama), charts externos
  (Helm), Vault/external-secrets, runners ARC `arc-k8s`.
- **Medición de cola** — `ci-queue/ci_queue.py` es la librería canónica de medición de cola y clasificación de
  labels de CI. Ningún otro sitio mide la cola por su cuenta. Encima viven ya (INFRA-550) el exportador
  `ci-queue/exporter.py` (Deployment en ns `monitoring`, métricas `ci_queue_*`) y su Application
  `infra/ci-queue-exporter.yaml`, ambos reutilizando esta librería. El scrape y las alertas están en
  `k8s-observability-pocharlies` (`manifests/arc-scrape.yaml`, `manifests/arc-rules.yaml`).
- **Dependen de él** — **todos los repos de la compañía**: su CI usa `reusable-ci.yml`; el chequeo de contratos es
  `scripts/check-contracts.py` (hook global y respaldo de CI); `docs/ci-cd-gitops-standard.md` es el estándar.
- **Applications que posee este repo (16: las 15 medidas por el CTO + `ci-queue-exporter`)**: `root`, `argocd`, `cert-manager`, `descheduler`,
  `external-dns`, `external-secrets`, `gpu-operator`, `harbor`, `kyverno`, `longhorn`, `metallb`, `nfs-cold`,
  `nfs-warm`, `reflector`, `velero`. Las 15 son **multi-source**: chart Helm externo + `values` de este repo; la
  16.ª, `ci-queue-exporter` (INFRA-550), es **single-source** `path: ci-queue` de este repo, sin chart (Kustomize
  con `configMapGenerator`). Todas con
  `targetRevision: deploy/prod`. Charts medidos: argo-cd 9.5.14, cert-manager v1.20.2, descheduler 0.36.0,
  external-dns 1.21.1, external-secrets 2.5.0, gpu-operator v26.3.1, harbor 1.19.0, kyverno 3.8.1, longhorn 1.13.0,
  metallb 0.15.3, reflector 10.0.65, velero 12.0.1.
- **Tronco**: **`deploy/prod`**. Además **registra** (sin ser dueño de su código) las Applications de ~40 apps de
  otros repos en `apps/*.yaml` y ~30 en `infra/*.yaml` (observability, traefik, arc, keda, kyverno…). `apps-disabled/`
  guarda las desactivadas (`shopify-back-in-stock`, `shopify-sync`, `skirmshop-competitor-crawler`).

## 3. Stack

| pieza | versión | para qué | no se usa en su lugar |
|---|---|---|---|
| ArgoCD | chart argo-cd 9.5.14 | GitOps (se autogestiona) | Flux |
| Kustomize raíz + `Application` YAML | — | listar apps | ApplicationSet (decisión previa; **pendiente confirmar**) |
| GitHub Actions reutilizables | — | CI/release | pipelines copiados por repo |
| Python 3.12 + PyYAML | CI | `tests/test_*.py` (contrato SRE foundation) | — |

## 4. Componentes compartidos

| concepto | pieza canónica | ruta | quién la usa |
|---|---|---|---|
| CI estándar | `reusable-ci.yml` (inputs `runner`, `run_node`, `run_docker_build`, `images`, `kustomize_paths`…) | `.github/workflows/` | todos los repos k8s |
| Release de imágenes | `reusable-release.yml` | ídem | repos con imagen propia |
| Release de manifiestos | `reusable-manifest-release.yml` | ídem | repos solo-manifiesto |
| Staging | `reusable-deploy-stg.yml` | ídem | repos con overlay `stg` |
| Estándar CI/CD | `docs/ci-cd-gitops-standard.md` | `docs/` | todos |
| Verificación de runners ARC | `scripts/verify_arc_runner_render.sh` | `scripts/` | CI |
| Medición de cola CI | `ci-queue/ci_queue.py` (cliente, clasificador, percentiles, pools) + CLI `scripts/ci_queue_report.py` | `ci-queue/`, `scripts/` | informe de diagnóstico y medición 48 h (INFRA-547/551) |
| Exporter de cola CI | `ci-queue/exporter.py` + `ci-queue/kustomization.yaml` (Deployment, Service, token por generator `GithubAccessToken` de external-secrets — sin PAT) | `ci-queue/`, Application `infra/ci-queue-exporter.yaml` | scrape `ci_queue_*` en ns monitoring → reglas ARC en observability (INFRA-550) |
| Runbooks | evacuar nodo, restore etcd/Velero, unseal de Vault | `docs/runbook-*.md` | operación |

## 5. Cómo se construye aquí

Una app nueva = `apps/<x>.yaml` (o `infra/<x>.yaml`) con su `Application` **y** una línea en `kustomization.yaml`
raíz; `prune: false` en las apps normales.

Retirar un recurso en una app con `prune: false`: se quita de git por PR y se poda con una operación de sync acotada a ese recurso (`operation.sync.prune: true` + `resources`), nunca con `prune` global ni `kubectl delete`; precedente: `hermes-despliegue poda` (SC-1574). El Secret de un ExternalSecret `Owner` se borra con su ES, aunque sea `deletionPolicy: Retain`. Lo creado a mano fuera de ArgoCD no lo poda nadie: borrado nombrado y firmado por el CTO (precedente: `galan-chat-alibaba`, DGX-634). Detalle y pasos: `nota-architect-patron-retiro-sin-mano.md` en DGX-619.

**Nunca** `kubectl delete` de una Application (el finalizer arrastra
workloads y PVC). Cambiar el `targetRevision` o `path` de una app existente (p. ej. `ai.yaml`, pinneada a un SHA con
rollbacks comentados) es un cambio de producción: PR + revisión, y no solo merge. `docs/audit-2026-05-22*` son
fotos históricas, no estado.

## 6. Tests y validaciones

```sh
python3 -m unittest discover -s tests -p 'test_*.py'     # contrato synapse-sre-foundation + librería ci-queue
kustomize build .                                         # reusable-ci con kustomize_paths ". ci-queue"
kustomize build ci-queue                                  # el exporter no cuelga del raíz: la CI lo construye aparte
bash scripts/verify_arc_runner_render.sh
python3 scripts/ci_queue_report.py --org pocharlies-org --days 7   # informe de cola (requiere gh auth)
```
Nº de tests: 58 (medido con `unittest discover` el 2026-10-08; 23 en `tests/test_ci_queue.py`, 11 en
`tests/test_ci_queue_exporter.py` y 1 en `tests/test_ci_queue_pools.py`, herméticos, fixtures en
`tests/fixtures/ci-queue/`).

## 7. CI/CD y despliegue

- `ci.yml` (`arc-k8s`): `standard` (reusable local, `kustomize_paths: ". ci-queue"`) + `synapse-sre-foundation-contract`.
- `release.yml` (tags / `workflow_dispatch image_tag`): llama a `reusable-ci.yml` local y publica.
- **Cambiar un reusable afecta a ~40 repos a la vez**: los repos que lo llaman por `@main` lo sufren al instante; los
  que lo pinnean por SHA no (p. ej. `ai`, `dgx-synapse-mcp` → `@ac96743b…`).
- Despliegue: merge a `deploy/prod` → app `root` sincroniza (auto) → crea/actualiza Applications. **Validación en
  producción**: `kubectl get applications -n argocd` (todas Synced/Healthy y ninguna `Unknown`); Synced ≠ funcionando
  (`/spec/replicas` en `ignoreDifferences`). Pendiente de ejecutar (sin kubectl).

## 8. Decisiones y trampas

- README desfasado (k3s v1.32.5, apunta a la org `pocharlies`): el cluster real es k3s v1.36.
- `infra/observability.yaml`, `infra/infra.yaml`, `traefik-*`, `arc*`, `keda`, `renovate`, `opencode`… tienen su
  Application **aquí** pero su código en otros repos (`k8s-observability`, `k8s-infra`, `dgx-infra`).
- `2026-08-14` · postmortem «renombrado y guerras del controlador» (`docs/postmortem-20260814-…md`): dos controladores
  peleando por el mismo recurso; leer antes de renombrar Applications.
- `bootstrap/app-of-apps.yaml` es el arranque manual del `root`; no se aplica en el día a día.
- La lista de pools válidos de runners = los `runnerScaleSetName` de `infra/arc.yaml` + los extras declarados en
  `ci-queue/ci_queue.py` (`EXTRA_POOLS`, p. ej. `x86-hermes`); fuente única, no se copia en ningún otro sitio.
  Excepción mecánica: el exporter monta `ci-queue/pools.txt`, copia DERIVADA (kustomize no lee ficheros fuera de
  su raíz); `tests/test_ci_queue_pools.py` falla si diverge de `infra/arc.yaml` y su mensaje trae el comando. Al
  cambiar un pool, desde la raíz del repo:
  `{ head -3 ci-queue/pools.txt; grep -E '^\s*runnerScaleSetName:' infra/arc.yaml; } > ci-queue/pools.txt.new &&
  mv ci-queue/pools.txt.new ci-queue/pools.txt`.
- Límite del exporter de cola (`ci-queue/exporter.py`): `status=queued` solo lista runs SIN ningún job arrancado;
  un job con label sin pool dentro de un run cuyos otros jobs ya corren es invisible. «En cola» se decide por el
  `status` del job, no por `started_at` (la API lo rellena en jobs que nunca tuvieron runner).
- La API de runs de la org (`GET /orgs/{org}/actions/runs`) responde 404 con token de usuario sin permisos de
  admin de Actions: la medición recorre repos (`ci-queue/ci_queue.py`). Con ~6000 runs/semana y 5000 llamadas/h
  de cuota, el diagnóstico de 7 días mide los runs rápidos con `run_started_at` — **aproximación a la baja**
  (un job `needs` o de otro pool dentro de un run rápido no se ve). Los asserts C1/C5 y las ventanas
  `--since/--hours` activan `exact=True`, que pide la API de jobs para todos los runs (~1700 llamadas para 48 h).
- `apps/ai-lab.yaml` (DGX-689): laboratorio de dgx3, FUERA del árbitro de cómputo. Application aparte de `ai` (que lleva los hooks del árbitro): renderiza solo `lab/` de `k8s-ai-pocharlies`, pinneada a un SHA de fusión, sin hooks y sin `ignoreDifferences` de réplicas (solo un PR cambia réplicas; el panel rechaza el `power` sobre `ai-lab`). `prune: true` en su namespace. Desde DGX-690 `lab/` lleva dos fases: el Job `qwen38-lab-prepare` (fase A, sin GPU, ya hecha) y el Deployment `qwen38-lab` (fase B: `replicas: 1` en el SHA `99e10cd0`, re-encendida tras el corte de CA de dgx3 para medir a reloj completo, relanzada en el SHA `3b79a2b0` (`launch-revision` -5, `UPS_GUARD=0`: dgx3 fuera del SAI); se apaga volviendo a `19a0591f` con `replicas: 0`; el motor se corta solo con el vigilante de memoria y del SAI de `serve.sh`); la `source` solo admite `repoURL`, `targetRevision` y `path` (sin `kustomize`). Marcha atrás: un PR que devuelve `targetRevision` al SHA anterior. Retirar la carga (Job y Deployment) = PR que vacía `lab/`. Retirar la Application misma = PR que quita `apps/ai-lab.yaml` y su línea en `kustomization.yaml` + poda acotada de `root` sobre `Application/ai-lab` (`operation.sync.prune: true` + `resources`, patrón de §5, precedente `hermes-despliegue poda`): `root` tiene `prune: false` y sin esa poda la Application se queda para siempre. El finalizer arrastra el Pod y el Namespace, no el hostPath `/srv/ai-lab`. Nunca `kubectl delete application`.

Última verificación contra el código: 2026-10-06 · a5698db (origin/deploy/prod)
