# Evidencia — INFRA-334 p95: runner caliente + pre-pull del motor en arc-k8s

Rama `INFRA-334-p95-warm-pool` contra `deploy/prod` (el tronco que lee la app
`root` de ArgoCD). Ejecutado en x86 (ubuntu), 2026-11-02/03.

## Medición del eslabón dominante (antes)

Comando (API de jobs por run, pilotos k8s-litellm-pocharlies + skirmshop-labels,
`workflow_runs?per_page=100` filtrando `PR review` success, job
`Review del PR (PR-Agent)`):

```
gh api /repos/pocharlies-org/<repo>/actions/runs/<id>/jobs   # cola = job.started_at - run.created_at
```

Resultado (n=42 jobs, 31-10 → 02-11, re-ejecuciones excluidas): PASS — confirma
el desglose de qa (70-qa.md id 30305): el motor cumple; dominan cola + pull.

```
cola        n=42  mediana 33,5 s   p90 85 s   p95 139 s
job         n=42  mediana 111 s    p95 214 s  (wall sin cola)
wait_pull   n=42  mediana 23,5 s   p90 107 s  p95 122 s  max 238 s (timeout paso 240 s)
motor       n=42  mediana 49,5 s   p95 98 s
wait>60 s: 10 de 42    job>90 s: 32 de 42
```

Dónde vive cada eslabón: cola = runner frío (minRunners 0: cada job pagaba pod
+ registro; ASRS `arc-k8s` live: `minRunners 0, maxRunners 32`); pull = imagen
del motor (253 MB, 13 capas) dentro del **dind efímero** del pod del runner
(volumen vacío por job; Harbor sirve desde ks5 y los runners caen en atlantic
(OVH) + ubuntu, así que desde atlantic el pull cruza el WAN).

## Imagen pineada servida anónima (base del pre-pull sin credenciales)

```
$ crane pull harbor.e-dani.com/homelab/pr-agent@sha256:42c7833a... img.tar   # sin login
real 0m18.9s   # 253 MB por LAN
```

## Render del ASRS (después)

Comando: `bash scripts/verify_arc_runner_render.sh` (helm template del chart
`gha-runner-scale-set` 0.14.1 con los values de `infra/arc.yaml`). PASS.

```
ARC runner render contract: OK
```

Diferencia sobre el ASRS renderizado (antes → después):

```
minRunners: 0 → 2
initContainers: [init-dind-externals, dind] →
                [init-dind-externals, dind, warm-pr-agent]
```

`warm-pr-agent`: sidecar nativo (`restartPolicy: Always`, el runner no espera su
fin), acotado (`timeout 240`), best-effort (`|| true`), sin credenciales, sin
privileged, monta `dind-sock`, imagen del runner pineada por digest.

## Validaciones

- `python3 -m unittest discover -s tests` → **Ran 100 tests, OK** (incluye el
  test nuevo `tests/test_arc_warm_pool.py` y los contadores actualizados de
  `test_arc_runner_ks5_placement.py`).
- `bash scripts/verify_arc_runner_render.sh` → **OK**.
- `kubectl apply --dry-run=server --server-side --force-conflicts -f asrs-only.yaml`
  → `serverside-applied (server dry run)`: el CRD acepta el template. Nota
  honesta: ARC 0.14.1 no registra webhook de validación (comprobado:
  `kubectl get validatingwebhookconfigurations | grep -i arc` → vacío), así que
  la validación del controlador se ejerce en el reconcile tras el sync — se
  vigila `kubectl get autoscalingrunnersets -n arc-runners` tras el despliegue
  (paso 5 del encargo, post-merge).

## Criterios

- C6 (INFRA-298, p95 del job de review < 90 s): esta PR ataca los dos eslabones
  que la medición señala como defecto — cola (minRunners 2) y pull (sidecar
  warm-pr-agent) — sin tocar el motor, el juez ni el digest fijado. La medida
  final post-despliegue (runs naturales + PRs de prueba) va como comentario de
  progreso en INFRA-334, no aquí.
