# INFRA-1407 (P1 de INFRA-1405) · evidencia — scale set ARC propio `arc-manifestguard`

Dónde: worktree de la rama `INFRA-1407-manifestguard-access` (desde origin/deploy/prod `b06f550`),
pod `company-0`, 16-11-2026. El scale set es un Helm release gestionado por ArgoCD (Application con
los values inline, como `arc-hermes` y `arc-openclaw`): cero `helm upgrade` a mano y cero `kubectl`.

El RBAC al que apunta (`arc-manifestguard-cr-reader`) y la NetworkPolicy del pool están en la PR
hermana de `pocharlies-org/k8s-infra-pocharlies` (rama homónima).

## 1. El Application nuevo se parsea junto a los seis existentes · PASS

```
python3 -c "yaml.safe_load_all(infra/arc.yaml)"
  8 documentos: arc (controller), arc-openclaw, arc-hermes, arc-k8s, arc-k8s-atlantic,
                arc-skills-eval, arc-manifestguard
  arc-manifestguard: chart gha-runner-scale-set 0.14.1, destino ns arc-runners
  values: runnerScaleSetName=arc-manifestguard  minRunners=0  maxRunners=2
          githubConfigUrl=https://github.com/pocharlies-org
          template.spec.serviceAccountName=arc-manifestguard-cr-reader
          containerMode: ausente (sin DinD)
```

## 2. Suite de contratos del repo · PASS

```
python3 -m unittest discover -s tests -p 'test_*.py'  -> Ran 135 tests ... OK
```

Incluye:
- `tests/test_arc_manifestguard_pool.py` (nuevo, 5 tests): identidad = el SA dedicado, scale set
  propio con min 0 / max 2, alcance org, sin DinD ni `privileged`, imagen pinada por digest,
  colocación en `workload=cpu` con el doble candado sobre los control planes y sin tolerar
  `role=edge`.
- `tests/test_ci_queue_pools.py`: `ci-queue/pools.txt` regenerado con el comando que documenta
  ARCHITECTURE.md §8 (`runnerScaleSetName: arc-manifestguard` al final de la lista).
- `tests/test_arc_runner_ks5_placement.py`: contadores de imágenes fijados a 14 runner / 4 dind /
  18 `IfNotPresent` (el pool nuevo aporta 1 runner y 1 `IfNotPresent`, ninguna imagen de dind).

## 3. Render contra el chart 0.14.1 · PENDIENTE DE CI (no ejecutable desde esta sesión)

`scripts/verify_arc_runner_render.sh` (lo corre `reusable-ci.yml`, l.289) renderiza ahora también
`arc-manifestguard` y fija: `runnerScaleSetName`, min 0 / max 2, ausencia de `runnerScaleSetLabels`,
`serviceAccountName == arc-manifestguard-cr-reader`, **que el chart no crea ningún ServiceAccount**
(con `template.spec.serviceAccountName` puesto, `no_permission_serviceaccount.yaml` queda fuera: la
identidad revisada es la de ArgoCD), un solo contenedor `runner`, sin `initContainers`, sin
`volumes`, sin `privileged` y sin `DOCKER_HOST`, más su fila en la matriz de elegibilidad de nodos
(atlantic y x86 sí; ks5-cp, sauvage y arm no).

No se ha podido ejecutar aquí: `helm template/pull oci://ghcr.io/...` responde `403` al endpoint de
token desde el pod de la sesión (medido el 16-11-2026). El script está validado con `bash -n` y sus
aserciones se corresponden con los values de arriba; si el render de CI diera una diferencia, se
corrige en esta misma rama.

## 4. Criterios de 00-spec.md

- **Scale set `arc-manifestguard` (min 0 / max 2) con `serviceAccountName` = el SA dedicado**:
  Application en `infra/arc.yaml`, values en git, entregado por ArgoCD. El `helm upgrade -f
  platform/arc/scale-set-k8s.yaml` que citaba la spec es el mecanismo **anterior**: aquel fichero se
  borró de `k8s-infra` en INFRA-960 (#420) y los scale sets viven hoy aquí como Applications
  (ARCHITECTURE.md §8 y `rbac-hermes-despliegue.yaml`). Se entrega por la vía equivalente y GitOps,
  sin `kubectl`.
- **No se ensancha `arc-k8s`**: el diff no toca el bloque `arc-k8s` ni su SA.
- **Frontera de privilegios**: el pool es de alcance org, así que cualquier workflow de la org que
  pida `runs-on: arc-manifestguard` obtiene un runner capaz de **leer** CRDs (sin escritura, sin
  secretos, sin DinD). Es lo que dictamina `security` en las dos PR.
- **Sin credenciales**: no hay Secret ni ExternalSecret nuevos; el token del SA lo proyecta kubelet.
- Lectura real de CRDs desde el runner y `Synced` de las Applications: se comprueban tras el merge
  (comandos en la PR de k8s-infra, §6).
