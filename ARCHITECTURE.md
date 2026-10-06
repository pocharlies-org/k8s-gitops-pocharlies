# ARCHITECTURE.md — k8s-gitops-pocharlies

> El orquestador **app-of-apps** de ArgoCD del cluster y la casa de los workflows reutilizables de CI/CD de la
> compañía. Es la raíz del despliegue: un error aquí afecta a todo el cluster. Base: `architect` (SC-1426,
> 01-10-2026); sección de CI compartida y realidad de las dos ramas añadidas por `devops` (DGX-625, 06-10-2026).

## 1. Clientes y versiones

| cliente | repositorio / ruta | versión desplegada | cómo se despliega |
|---|---|---|---|
| App-of-apps `root` | `kustomization.yaml` raíz → `infra/*.yaml`, `apps/*.yaml`, `legacy/*.yaml`, `bootstrap/app-of-apps.yaml` | `origin/deploy/prod` | ArgoCD app `root` (path `.`, `targetRevision: deploy/prod`; medido 06-10-2026 con `kubectl get application root`) |
| Workflows reutilizables | `.github/workflows/reusable-{ci,release,manifest-release,manifest-pr-release,deploy-stg,pr-review,duplicados,alibaba-key-guard}.yml` | se consumen desde **`main`** como `@main` o por SHA | cada repo `k8s-*` los llama |

Un solo «cliente» para el despliegue: ArgoCD. Los consumidores del marco de CI son ~115 repos de la org (vía
GitHub Actions, no vía ArgoCD).

**Dos ramas vivas con papeles distintos** (medido 06-10-2026): `deploy/prod` es el tronco que lee ArgoCD
(manifiestos, `ci-queue/`, este documento); `main` es la rama que sirve los reutilizables (todo lo de §4). No es
un ciclo merge→trunk limpio entre ellas: quien cambie una pieza que vive en ambas debe llevar el cambio a las dos.

## 2. Dependencias, en ambos sentidos

- **Depende de** — cada repo `k8s-*` y `dgx-infra` (cada `Application` apunta a su repo/rama), charts externos
  (Helm), Vault/external-secrets, runners ARC `arc-k8s`.
- **Medición de cola** — `ci-queue/ci_queue.py` (rama `deploy/prod`) es la librería canónica de medición de cola
  y clasificación de labels de CI. Ningún otro sitio mide la cola por su cuenta.
- **Dependen de él** — **todos los repos de la compañía**: su CI usa `reusable-ci.yml`; el chequeo de contratos es
  `scripts/check-contracts.py` (hook global y respaldo de CI); `docs/ci-cd-gitops-standard.md` es el estándar;
  los guards `duplicados` y `alibaba-key-guard` se cablean desde `templates/ci/`.
- **Applications que posee este repo (15)**: `root`, `argocd`, `cert-manager`, `descheduler`, `external-dns`,
  `external-secrets`, `gpu-operator`, `harbor`, `kyverno`, `longhorn`, `metallb`, `nfs-cold`, `nfs-warm`,
  `reflector`, `velero`. Todas **multi-source**: chart Helm externo + `values` de este repo, con
  `targetRevision: deploy/prod`.
- **Tronco de despliegue**: **`deploy/prod`**. Además **registra** (sin ser dueño de su código) las Applications
  de ~40 apps de otros repos en `apps/*.yaml` y ~30 en `infra/*.yaml` (observability, traefik, arc, keda,
  kyverno…). `apps-disabled/` guarda las desactivadas.

## 3. Stack

| pieza | versión | para qué | no se usa en su lugar |
|---|---|---|---|
| ArgoCD | chart argo-cd | GitOps (se autogestiona) | Flux |
| Kustomize raíz + `Application` YAML | — | listar apps | ApplicationSet (decisión previa) |
| GitHub Actions reutilizables | — | CI/release | pipelines copiados por repo |
| Python 3.12 + PyYAML | CI | `tests/test_*.py`, `scripts/check-*.py` | — |
| jscpd (vía `npx`, versión fijada en `scripts/duplicados.py`) | job duplicados | detector de copia | grep inline por repo |

## 4. Marco de CI compartida (la razón de ser de `main`)

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

**Este repo se cablea `duplicados` y `pr-review`, y NO se cablea `alibaba-key-guard`**: su propio
`scripts/alibaba-key-guard.py` contiene literalmente los patrones que busca (docstring + tupla `PATRONES`) y el
job saldría rojo contra el detector — medido en DGX-625: 6 hits, todos dentro del propio script.

## 5. Cómo se construye aquí

Una app nueva = `apps/<x>.yaml` (o `infra/<x>.yaml`) con su `Application` **y** una línea en
`kustomization.yaml` raíz; `prune: false` en las apps normales. **Nunca** `kubectl delete` de una Application (el
finalizer arrastra workloads y PVC). Cambiar el `targetRevision` o `path` de una app existente es un cambio de
producción: PR + revisión. Un cambio al marco de CI (§4) afecta a ~115 repos: los que llaman por `@main` lo
sufren al instante; los que pinean por SHA no.

## 6. Tests y validaciones

```sh
python3 -m unittest discover -s tests -p 'test_*.py'     # contrato synapse-sre-foundation, ci-queue, duplicados…
python3 scripts/test-alibaba-key-guard.py                # self-check del guard (DGX-625), fixture en tmp
python3 scripts/check-workflow-pins.py                   # regla de pins de §4
python3 scripts/test-check-contracts.py                  # reglas de contratos
kustomize build .                                        # reusable-ci con kustomize_paths "."
bash scripts/verify_arc_runner_render.sh
```

## 7. CI/CD y despliegue

- `ci.yml` (`arc-k8s`): `standard` (reusable local, `kustomize_paths: "."`) + contrato synapse-sre-foundation +
  los `check-*.py` y unittests de §6.
- `release.yml` (tags / `workflow_dispatch image_tag`): llama a `reusable-ci.yml` local y publica.
- Despliegue: merge a `deploy/prod` → app `root` sincroniza (auto) → crea/actualiza Applications. **Validación en
  producción**: `kubectl get applications -n argocd` (todas Synced/Healthy, ninguna `Unknown`); Synced ≠
  funcionando (`/spec/replicas` en `ignoreDifferences`).

## 8. Decisiones y trampas

- **Dos ramas, dos verdades** (§1): el documento existía solo en `deploy/prod` y el marco de CI solo en `main`
  (medido 06-10-2026). Un PR a `main` no despliega nada; un merge a `deploy/prod` no publica ningún reusable.
- README desfasado (k3s v1.32.5, org `pocharlies`): el cluster real es k3s v1.36+.
- `infra/observability.yaml`, `traefik-*`, `arc*`, `keda`… tienen su Application **aquí** pero su código en
  otros repos.
- `2026-08-14` · postmortem «renombrado y guerras del controlador» (`docs/postmortem-20260814-…md`): leer antes
  de renombrar Applications.
- `bootstrap/app-of-apps.yaml` es el arranque manual del `root`; no se aplica en el día a día.
- La lista de pools válidos de runners = los `runnerScaleSetName` de `infra/arc.yaml` + `EXTRA_POOLS` de
  `ci-queue/ci_queue.py`; fuente única.
- El guard de Alibaba es **CI**: no toca el cluster. La pieza Kyverno (`ClusterPolicy`, DGX-626) vive en
  `k8s-infra-pocharlies/platform/kyverno/policies.yaml` y es la que cubre lo creado a mano.

Última verificación contra el código: 2026-10-06 · trabajo DGX-625 sobre `origin/main` (mediciones de ramas por
`devops` con `kubectl` + índices de checkout; re-verificar tras el merge).
