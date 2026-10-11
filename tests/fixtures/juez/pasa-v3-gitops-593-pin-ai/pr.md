DGX-820: app ai a la ventana de los Sparks (92fb200, residente parado para la prueba del kernel 64K)

Jira: DGX-787

`apps/ai.yaml` pasa de `01f9b4da163dcf4626e6d33db0c450fababd7e10` (path `overlays/qwen38-tp3-ventana-20261010`) a `92fb20060dcb84ceb624c95b6a1090a48e824f76` con el path `overlays/sparks-ventana-20261010`, la ventana de DGX-810 (#581, #586) que ya se usó el 10-10. Es la ventana para la prueba del kernel de 64K (P1 de DGX-787), autorizada por Dani el 11-10. Para reiniciar dgx1 y dgx2 hay que parar el residente qwen38 TP=3 sin `kubectl scale` y sin el perfil creative (P1-9 de `scripts/glm53/README.md` en dgx-infra); esta ventana lo hace por gitops.

## Alcance de esta PR

- C1: la app ai pasa a la ventana de los Sparks (92fb200, overlays/sparks-ventana-20261010) sin Deployments de qwen38, con el rollback a qwen38 TP=3

## Qué cambia

- `targetRevision` y `path` de `apps/ai.yaml`, y un comentario con el efecto y el rollback. Nada más.
- El PreSync `llm-deploy-pause` deja el árbitro en `sync-paused` y la voz (omnivoice-tts-nvfp4, stt-turbo) a 0. El prune retira `qwen38-flash-next-head`, `-worker`, `-worker-dgx3`, el PostSync `llm-deploy-resume` y el PV/PVC `hf-cache-dgx1-dgx3-llm-ro` (PV Retain, el NFS no se toca).
- Entran los Jobs de la sonda de NCCL (v1, v2 y v3c, uno por Spark, 1 GPU cada uno). Corren una vez.
- El residente no vuelve hasta que los tres nodos estén en el kernel que se decida.

## Rollback

Volver a qwen38 TP=3: `01f9b4da163dcf4626e6d33db0c450fababd7e10` con path `overlays/qwen38-tp3-ventana-20261010`.

## Verificación

Render de `overlays/sparks-ventana-20261010` en `92fb200` con `kubectl kustomize` (44 documentos), comparado con el de `01f9b4d`:

- Deployments en el render: solo `vllm-vision-deep`, con `replicas: 0`. Ningún Deployment ni StatefulSet de qwen38.
- Solo en el render de qwen38 (lo que se retira): los tres Deployments de qwen38, `llm-deploy-resume` y el PV/PVC `hf-cache-dgx1-dgx3-llm-ro`.
- Solo en el render de la ventana (lo que entra): el ConfigMap `sparks-nccl-sonda` y los nueve Jobs `sparks-nccl-sonda*`.
- Los Jobs `qwen38fn-tp3-convert`, `-publish` y `-serve` salen idénticos en los dos renders y están Complete en el cluster (no se relanzan). El único objeto distinto es el ConfigMap `qwen38-flash-next-vllm-launch`, que sin Deployment no lo monta nadie.
- El hook de pausa es el único PreSync del render; su puerta acepta `phase: ready` con `desired_mode == effective_mode`, y el árbitro lee ahora `llm-tp`, `ready`, sin blockers.
- `92fb200` está en k8s-ai en `origin/pin/sparks-ventana-20261010`. `apps/ai.yaml` parsea como YAML con el `targetRevision` y el `path` de arriba.

Riesgo a vigilar en la ventana: los Jobs de sonda v1 y v2 dieron FALLA el 10-10; si fallan otra vez, la app `ai` queda Degraded mientras dure la ventana. Cada sonda pide la GPU de su Spark: conviene que hayan terminado antes del `dispram` y el `arm` (`nvidia-smi --query-compute-apps=pid` vacío).

La PR no se fusiona hasta que security y preflight den el visto bueno. No se ha tocado el cluster.

🤖 Generated with [Claude Code](https://claude.com/claude-code)


