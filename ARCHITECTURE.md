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
  labels de CI. Ningún otro sitio mide la cola por su cuenta. (En INFRA-550 se añadirán encima el exportador
  `ci-queue/exporter.py` y su Application `infra/ci-queue-exporter.yaml`, que reutilizan esta librería; hoy no
  existen todavía.)
- **Dependen de él** — **todos los repos de la compañía**: su CI usa `reusable-ci.yml`; el chequeo de contratos es
  `scripts/check-contracts.py` (hook global y respaldo de CI); `docs/ci-cd-gitops-standard.md` es el estándar.
- **Applications que posee este repo (15, medidas por el CTO)**: `root`, `argocd`, `cert-manager`, `descheduler`,
  `external-dns`, `external-secrets`, `gpu-operator`, `harbor`, `kyverno`, `longhorn`, `metallb`, `nfs-cold`,
  `nfs-warm`, `reflector`, `velero`. Todas **multi-source**: chart Helm externo + `values` de este repo, con
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
| Medición de cola CI | `ci-queue/ci_queue.py` (cliente, clasificador, percentiles, pools) + CLI `scripts/ci_queue_report.py` | `ci-queue/`, `scripts/` | informe de diagnóstico y medición 48 h (INFRA-547/551); el exporter de INFRA-550 la reutilizará |
| Runbooks | evacuar nodo, restore etcd/Velero, unseal de Vault | `docs/runbook-*.md` | operación |

## 5. Cómo se construye aquí

Una app nueva = `apps/<x>.yaml` (o `infra/<x>.yaml`) con su `Application` **y** una línea en `kustomization.yaml`
raíz; `prune: false` en las apps normales. **Nunca** `kubectl delete` de una Application (el finalizer arrastra
workloads y PVC). Cambiar el `targetRevision` o `path` de una app existente (p. ej. `ai.yaml`, pinneada a un SHA con
rollbacks comentados) es un cambio de producción: PR + revisión, y no solo merge. `docs/audit-2026-05-22*` son
fotos históricas, no estado.

## 6. Tests y validaciones

```sh
python3 -m unittest discover -s tests -p 'test_*.py'     # contrato synapse-sre-foundation + librería ci-queue
kustomize build .                                         # reusable-ci con kustomize_paths "."
bash scripts/verify_arc_runner_render.sh
python3 scripts/ci_queue_report.py --org pocharlies-org --days 7   # informe de cola (requiere gh auth)
```
Nº de tests: 38 (medido con `unittest discover` el 2026-10-05; 23 de ellos en `tests/test_ci_queue.py`,
herméticos, fixtures en `tests/fixtures/ci-queue/`).

## 7. CI/CD y despliegue

- `ci.yml` (`arc-k8s`): `standard` (reusable local, `kustomize_paths: "."`) + `synapse-sre-foundation-contract`.
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
- La API de runs de la org (`GET /orgs/{org}/actions/runs`) responde 404 con token de usuario sin permisos de
  admin de Actions: la medición recorre repos (`ci-queue/ci_queue.py`). Con ~6000 runs/semana y 5000 llamadas/h
  de cuota, el diagnóstico de 7 días mide los runs rápidos con `run_started_at` — **aproximación a la baja**
  (un job `needs` o de otro pool dentro de un run rápido no se ve). Los asserts C1/C5 y las ventanas
  `--since/--hours` activan `exact=True`, que pide la API de jobs para todos los runs (~1700 llamadas para 48 h).

Última verificación contra el código: 2026-10-01 · f2a8ce0 (origin/deploy/prod)
