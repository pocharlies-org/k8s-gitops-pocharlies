DGX-815: encender buildkitd-arm64-dgx3 (replicas 1, temporal) para el build de la imagen nccl-ring

Jira: DGX-815

Enciende `buildkitd-arm64-dgx3` (`replicas: 0` a `1`) en `buildkit/buildkitd-arm64-dgx3.yaml`. Es el mismo gesto que #274 de DGX-796, esta vez para que `build-nccl-ring-image.yml` (k8s-ai-pocharlies#153) construya la imagen `nccl-ring` de DGX-815. El diff es una línea más el comentario de la cabecera, que ahora dice que el encendido es temporal.

## Es temporal

Cuando el build termine, `replicas: 0` vuelve en una PR hermana de una línea, como #278 de DGX-796. El PVC de caché se queda. El resto del manifiesto no cambia.

## dgx3 está libre

Leído antes de abrir la PR, solo con `kubectl get`:

- `gpu-arbiter-state`: `effective_mode: llm-tp`, `phase: sync-paused` (no `switching`), con la ventana de los Sparks abierta.
- En dgx3 solo hay pods de sistema (gpu-operator, monitoring, velero) y Jobs en Completed en `llm` (`qwen38fn-tp3-*`, `sparks-nccl-sonda-*`). No hay carga del residente.
- El builder no pide GPU.
- El PVC `buildkitd-arm64-dgx3-cache` ya está Bound.

## Sobre #275

INFRA-826 (#275) anota el PVC más abajo en este mismo fichero (hunk en `PersistentVolumeClaim`). No hay solape con este diff y no la toco.

## Alcance de esta PR

- C3: el builder arm64 de dgx3 queda encendido para que el workflow de CI construya la imagen para linux/arm64 y la suba a Harbor por digest.

## Verificación

- `kubectl kustomize buildkit` renderiza sin error.
- `git diff`: `replicas: 0` a `1` y las líneas de comentario de la cabecera.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

