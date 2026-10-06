# ARCHITECTURE.md — k8s-gitops-pocharlies

> El orquestador **app-of-apps** de ArgoCD del cluster y la casa de los workflows reutilizables de CI/CD de la
> compañía. Es la raíz del despliegue: un error aquí afecta a todo el cluster. Base: `architect` (SC-1426,
> 01-10-2026); marco de CI compartida y realidad de las dos ramas añadidos por `devops` (DGX-625, 06-10-2026)
> como **superconjunto** de la versión de `deploy/prod` — nada de esa versión se ha quitado.

## 1. Clientes y versiones

| cliente | repositorio / ruta | versión desplegada | cómo se despliega |
|---|---|---|---|
| App-of-apps `root` | `kustomization.yaml` raíz → `infra/*.yaml`, `apps/*.yaml`, `legacy/*.yaml`, `bootstrap/app-of-apps.yaml` | `origin/deploy/prod` = f2a8ce0 (medido 2026-10-01) | ArgoCD app `root` (path `.`, `targetRevision: deploy/prod`; verificado 06-10-2026 con `kubectl get application root`) |
| Workflows reutilizables | `.github/workflows/reusable-{ci,release,manifest-release,manifest-pr-release,deploy-stg,pr-review,duplicados,alibaba-key-guard}.yml` | se sirven desde **`main`** y se consumen como `@main` o por SHA (`@ac96743b…`) | cada repo `k8s-*` los llama |

Un solo «cliente» para el despliegue: ArgoCD. Los consumidores del marco de CI son ~115 repos de la org (vía
GitHub Actions, no vía ArgoCD).

**Dos ramas vivas con papeles distintos** (medido 06-10-2026): `deploy/prod` es el tronco que lee ArgoCD
(manifiestos, `ci-queue/`, este documento); `main` es la rama que sirve los reutilizables (todo lo de §4). No es
un ciclo merge→trunk limpio entre ellas: quien cambie una pieza que vive en ambas debe llevar el cambio a las dos.
El `kustomization.yaml` raíz también difiere entre ramas: el que se aplica es el de `deploy/prod`.

## 2. Dependencias, en ambos sentidos

- **Depende de** — cada repo `k8s-*` y `dgx-infra` (cada `Application` apunta a su repo/rama), charts externos
  (Helm), Vault/external-secrets, runners ARC `arc-k8s`.
- **Medición de cola** — `ci-queue/ci_queue.py` es la librería canónica de medición de cola y clasificación de
  labels de CI. Ningún otro sitio mide la cola por su cuenta. (En INFRA-550 se añadirán encima el exportador
  `ci-queue/exporter.py` y su Application `infra/ci-queue-exporter.yaml`, que reutilizan esta librería; hoy no
  existen todavía.) **`ci-queue/` solo existe en `deploy/prod`**: en `main` no está el directorio.
- **Dependen de él** — **todos los repos de la compañía**: su CI usa `reusable-ci.yml`; el chequeo de contratos es
  `scripts/check-contracts.py` (hook global y respaldo de CI); `docs/ci-cd-gitops-standard.md` es el estándar;
  los guards `duplicados` y `alibaba-key-guard` se cablean desde `templates/ci/`.
- **Applications que posee este repo (15, medidas por el CTO)**: `root`, `argocd`, `cert-manager`, `descheduler`,
  `external-dns`, `external-secrets`, `gpu-operator`, `harbor`, `kyverno`, `longhorn`, `metallb`, `nfs-cold`,
  `nfs-warm`, `reflector`, `velero`. Todas **multi-source**: chart Helm externo + `values` de este repo, con
  `targetRevision: deploy/prod`. Charts medidos 2026-10-01: argo-cd 9.5.14, cert-manager v1.20.2, descheduler
  0.36.0, external-dns 1.21.1, external-secrets 2.5.0, gpu-operator v26.3.1, harbor 1.19.0, kyverno 3.8.1,
  longhorn 1.13.0, metallb 0.15.3, reflector 10.0.65, velero 12.0.1.
- **Tronco de despliegue**: **`deploy/prod`**. Además **registra** (sin ser dueño de su código) las Applications de
  ~40 apps de otros repos en `apps/*.yaml` y ~30 en `infra/*.yaml` (observability, traefik, arc, keda,
  kyverno…). `apps-disabled/` guarda las desactivadas (`shopify-back-in-stock`, `shopify-sync`,
  `skirmshop-competitor-crawler`).

## 3. Stack

| pieza | versión | para qué | no se usa en su lugar |
|---|---|---|---|
| ArgoCD | chart argo-cd 9.5.14 | GitOps (se autogestiona) | Flux |
| Kustomize raíz + `Application` YAML | — | listar apps | ApplicationSet (decisión previa; **pendiente confirmar**) |
| GitHub Actions reutilizables | — | CI/release | pipelines copiados por repo |
| Python 3.12 + PyYAML | CI | `tests/test_*.py` (contrato SRE foundation), `scripts/check-*.py` | — |
| jscpd (vía `npx`, versión fijada en `scripts/duplicados.py`) | job duplicados | detector de copia | grep inline por repo |

## 4. Componentes compartidos

| concepto | pieza canónica | ruta | quién la usa |
|---|---|---|---|
| CI estándar | `reusable-ci.yml` (inputs `runner`, `run_node`, `run_docker_build`, `images`, `kustomize_paths`…) | `.github/workflows/` | todos los repos k8s |
| Release de imágenes | `reusable-release.yml` | ídem | repos con imagen propia |
| Release de manifiestos | `reusable-manifest-release.yml` (+ `reusable-manifest-pr-release.yml`) | ídem | repos solo-manifiesto |
| Staging | `reusable-deploy-stg.yml` | ídem | repos con overlay `stg` |
| Guard de código duplicado | `reusable-duplicados.yml` (lógica en `scripts/duplicados.py`, jscpd) | `.github/workflows/`, `scripts/` | repos cableados vía `templates/ci/duplicados.yml` |
| Guard contra keys directas de Alibaba | `reusable-alibaba-key-guard.yml` (lógica en `scripts/alibaba-key-guard.py`, DGX-619/625) | `.github/workflows/`, `scripts/` | repos cableados vía `templates/ci/alibaba-key-guard.yml` |
| Regla de pins | `scripts/check-workflow-pins.py` | `scripts/` | CI de este repo y consumidores |
| Chequeo de contratos | `scripts/check-contracts.py` | `scripts/` | hook global y CI de todos los repos |
| Marco de `pr-review` | `reusable-pr-review.yml` + `scripts/{review-{context,distribute,health},pr-agent-auth-check}.py` y `review_http.py`, esquema `schemas/pr_review.v1.json`, acciones `.github/actions/llm-review` y `.github/actions/notify-telegram` | `.github/`, `scripts/`, `schemas/` | revisión de PRs de la org (cable vía `templates/ci/pr-review.yml`; docs en `docs/ci-pr-review.md`); `pr-agent-auth-check.py` es el ÚNICO sitio que decide credencial rota (401/403) de PR-Agent, solo sobre líneas ERROR/WARNING/CRITICAL o traceback (INFRA-620) |
| Cable por repo | `templates/ci/*.yml` (`duplicados`, `pr-review`, `alibaba-key-guard`) | `templates/ci/` | cada repo lo copia a `.github/workflows/<job>.yml` |
| Auto-instalación de ArgoCD | `argocd/values.yaml` (valores Helm que consume la Application `argocd` de `deploy/prod`), `argocd/ingressroute.yaml`, `argocd/repositories.yaml` (**generado por `argocd/gen_repositories.py`: editar el generador, no el fichero**) | `argocd/` | el `kustomization.yaml` raíz lista los dos últimos |
| Estándar CI/CD | `docs/ci-cd-gitops-standard.md` | `docs/` | todos |
| Verificación de runners ARC | `scripts/verify_arc_runner_render.sh` **(solo en `deploy/prod`)** | `scripts/` | CI |
| Medición de cola CI | `ci-queue/ci_queue.py` (cliente, clasificador, percentiles, pools) + CLI `scripts/ci_queue_report.py` **(ambos solo en `deploy/prod`)** | `ci-queue/`, `scripts/` | informe de diagnóstico y medición 48 h (INFRA-547/551); el exporter de INFRA-550 la reutilizará |
| Runbooks | evacuar nodo, restore etcd/Velero, unseal de Vault | `docs/runbook-*.md` | operación |
| Docs y memoria del repo | postmortems, `docs/audit-2026-05-22*` (fotos históricas, no estado), `docs/archivo/`, `docs/ci-pr-review.md` | `docs/` | humanos |

### 4 bis. Marco de CI compartida (las tres capas, la razón de ser de `main`)

Tres capas, siempre en este orden — la lógica **nunca** se copia al repo consumidor:

| capa | dónde | qué es |
|---|---|---|
| orquestación | `.github/workflows/reusable-*.yml` | `workflow_call`: runner, secrets, checkout del framework |
| lógica | `scripts/*.py` | `check-contracts.py` (contratos `CONTRACTS.yaml`/`# CONTRACT:`), `check-workflow-pins.py` (pins), `duplicados.py` (código copiado), `alibaba-key-guard.py` (keys directas de Alibaba, DGX-619) |
| cable por repo | `templates/ci/<job>.yml` | ~10 líneas que cada repo copia a `.github/workflows/<job>.yml` |

Cada reutilizable se trae el framework con `actions/checkout` a un subdirectorio (`job.workflow_* ||` con
fallback al framework) y ejecuta el script a mano — `uses: ./` dentro de un reutilizable se resuelve contra el
workspace de quien llama, y `check-workflow-pins.py` lo rechazaría. Los inputs entran **por entorno**, nunca
interpolados en un `run` (lo rechaza el mismo pins). Los jobs corren en `arc-k8s`; Node solo donde hace falta
(duplicados), verificado por sha256.

**Regla de pins** (lo que vigila `check-workflow-pins.py`, CI de este repo lo ejecuta): todo `uses:` es `./`, un
SHA de 40 hex, o `pocharlies-org/k8s-gitops-pocharlies/...@main` — el único `@main` admitido, porque es este
mismo repo (mismo límite de confianza que `./`; un SHA propio sería imposible de escribir en el commit que cambia
la acción). Cualquier otra rama o tag de tercero es violación.

**Cómo cablea un repo una plantilla**: copiar `templates/ci/<job>.yml` tal cual a `.github/workflows/<job>.yml`;
los secretos de organización entran con `secrets: inherit`; los ajustes por repo van en `with:` (p. ej.
`permitidos` en alibaba-key-guard). El nombre del check (`<job> / <job>`) es lo que exige el guardia de merge:
no cambiar `name:` ni la clave del job. Validar sin abrir PR: `workflow_dispatch` (escanea el último commit del
tronco).

**Superficie estable**: la ruta del reusable, los nombres de sus inputs (`runner`, `permitidos`…) y el nombre del
check `<job> / <job>` no se renombran ni se quitan; un cambio breaking es un `reusable-<job>-v2.yml` al lado con
el viejo marcado deprecado. (No hay `CONTRACTS.yaml` en este repo: `duplicados` y `pr-review` tampoco lo tienen;
`check-contracts.py` guarda los de los repos consumidores.)

**Este repo se cablea `duplicados` y `pr-review`, y NO se cablea `alibaba-key-guard`**: su propio
`scripts/alibaba-key-guard.py` contiene literalmente los patrones que busca (docstring + tupla `PATRONES`) y el
job saldría rojo contra el detector — medido en DGX-625: 6 hits, todos dentro del propio script.

## 5. Cómo se construye aquí

Una app nueva = `apps/<x>.yaml` (o `infra/<x>.yaml`) con su `Application` **y** una línea en `kustomization.yaml`
raíz; `prune: false` en las apps normales. **Nunca** `kubectl delete` de una Application (el finalizer arrastra
workloads y PVC). Cambiar el `targetRevision` o `path` de una app existente (p. ej. `ai.yaml`, pinneada a un SHA con
rollbacks comentados) es un cambio de producción: PR + revisión, y no solo merge. `docs/audit-2026-05-22*` son
fotos históricas, no estado. Un cambio al marco de CI (§4) afecta a ~115 repos: los que llaman por `@main` lo
sufren al instante; los que pinean por SHA no.

## 6. Tests y validaciones

En `deploy/prod` (medido 2026-10-05):

```sh
python3 -m unittest discover -s tests -p 'test_*.py'     # contrato synapse-sre-foundation + librería ci-queue
kustomize build .                                         # reusable-ci con kustomize_paths "."
bash scripts/verify_arc_runner_render.sh
python3 scripts/ci_queue_report.py --org pocharlies-org --days 7   # informe de cola (requiere gh auth)
```

Nº de tests: 38 (medido con `unittest discover` el 2026-10-05; 23 de ellos en `tests/test_ci_queue.py`,
herméticos, fixtures en `tests/fixtures/ci-queue/`).

En `main` (medido 2026-10-06):

```sh
python3 -m unittest discover -s tests -p 'test_*.py'     # 153 tests: contratos de release, pr-review, duplicados, synapse-sre-foundation…
python3 scripts/test-alibaba-key-guard.py                # self-check del guard (DGX-625), fixture en tmp
python3 scripts/test-pr-agent-auth-check.py            # self-check del detector de credencial rota de PR-Agent (INFRA-620)
python3 scripts/test-check-contracts.py                  # reglas de contratos
python3 scripts/check-workflow-pins.py                   # regla de pins de §4
kustomize build .
```

## 7. CI/CD y despliegue

- `ci.yml` (`arc-k8s`): `standard` (reusable local, `kustomize_paths: "."`) + `synapse-sre-foundation-contract`
  + el job `release-contract`, que lista cada suite (`check-*.py`, los `tests/test_*.py` y desde DGX-625/INFRA-620 también
  `scripts/test-alibaba-key-guard.py` y `scripts/test-pr-agent-auth-check.py`).
- `release.yml` (tags / `workflow_dispatch image_tag`): llama a `reusable-ci.yml` local y publica.
- **Cambiar un reusable afecta a ~40 repos a la vez**: los repos que lo llaman por `@main` lo sufren al instante; los
  que lo pinnean por SHA no (p. ej. `ai`, `dgx-synapse-mcp` → `@ac96743b…`).
- Despliegue: merge a `deploy/prod` → app `root` sincroniza (auto) → crea/actualiza Applications. **Validación en
  producción**: `kubectl get applications -n argocd` (todas Synced/Healthy y ninguna `Unknown`); Synced ≠ funcionando
  (`/spec/replicas` en `ignoreDifferences`).

## 8. Decisiones y trampas

- **Dos ramas, dos verdades** (§1): el documento existía solo en `deploy/prod` y el marco de CI solo en `main`
  (medido 06-10-2026). Un PR a `main` no despliega nada; un merge a `deploy/prod` no publica ningún reusable. Tras
  el merge de este documento, llevarlo también a `deploy/prod` (PR aparte, inocuo para ArgoCD).
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
- El guard de Alibaba es **CI**: no toca el cluster. La pieza Kyverno (`ClusterPolicy`, DGX-626) vive en
  `k8s-infra-pocharlies/platform/kyverno/policies.yaml` y es la que cubre lo creado a mano.

Última verificación contra el código: 2026-10-01 · f2a8ce0 (`deploy/prod`, SC-1426) y 2026-10-06 · superconjunto
DGX-625 sobre `origin/main` (mediciones de ramas por `devops` con `kubectl` + índices de checkout; re-verificar
tras el merge).
