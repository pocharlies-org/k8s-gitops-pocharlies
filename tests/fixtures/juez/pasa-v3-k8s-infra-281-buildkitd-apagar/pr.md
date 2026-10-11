DGX-815: apagar buildkitd-arm64-dgx3 (replicas 0) tras el build de la imagen nccl-ring

DGX-815: apagar buildkitd-arm64-dgx3 (replicas 0) tras el build de la imagen nccl-ring

## Qué cambia

El builder de dgx3 se encendió con #279 para construir la imagen nccl-ring (run 38065099975, digest sha256:79db26e7…). Esa imagen ya está en Harbor, así que el builder vuelve a `replicas: 0`, igual que hizo #278 tras el build de la imagen GLM. Se quita también el texto de «TEMPORAL» que dejó #279 en la cabecera del manifiesto. El PVC de caché se queda.

Con esto dgx3 no tiene carga de buildkit y queda libre para el rango 2 del qwen38 TP=3 (DGX-817).

Un solo fichero: `buildkit/buildkitd-arm64-dgx3.yaml` (la línea `replicas` y el comentario de cabecera). Sin tocar el cluster: ArgoCD (`k8s-infra`, tronco `main`, sync automático) aplica el cambio al fusionar.

## Alcance de esta PR

- C6: el builder de dgx3 vuelve a 0 y no queda carga en dgx3

## Verificación

- `git diff origin/main --stat`: 1 fichero, 5 inserciones, 6 borrados.
- `yaml.safe_load_all` sobre el manifiesto: parsea bien. `grep -n replicas buildkit/buildkitd-arm64-dgx3.yaml` solo muestra el `replicas: 0` del Deployment.

Jira: DGX-815

🤖 Generated with [Claude Code](https://claude.com/claude-code)

