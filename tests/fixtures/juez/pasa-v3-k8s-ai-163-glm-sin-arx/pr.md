DGX-818: GLM TP=3 de la ventana sin ARX (experimento de aislamiento) y NCCL_DEBUG_SUBSYS con PROXY

## Alcance de esta PR

- C3: experimento sin ARX en el overlay de la ventana

## Qué hace

Tercer arranque de GLM-5.3-Flash TP=3 en la ventana: **experimento de aislamiento** que apaga ARX solo en `overlays/glm53-tp3-ventana-k4-20261010`. El segundo arranque (b3f92e8) pasa el rendezvous por la LAN, NCCL hace `Init COMPLETE` en los tres rangos y ARX se inicializa; después el anillo NCCL se queda a medias (nunca «Connected all rings», ~2 de 4 canales por rango), el worker no lee pesos y la API no escucha. qwen38 TP=3 con la misma lib parcheada, el mismo grafo y el mismo entorno NCCL pero sin ARX conecta.

- `VLLM_ARX_ALLREDUCE=0` en el ConfigMap `glm53-tp3-recipe` del overlay. Es el interruptor real: el `cuda_communicator.py` de kindling (a3c3a1d7) solo construye `ArxCommunicator` con `== "1"` y `ArxBig` solo si existe el anterior; sin él, all-reduce, reduce-scatter y all-gather caen a PyNccl. El entrypoint de la imagen no menciona ninguna `VLLM_ARX_*` (grep del checkout), así que el valor llega tal cual.
- `VLLM_GLM_ARX_PREFETCH=0`: el único otro mando que solo vale con ARX. `VLLM_ARX_RING`, `ARX_RING_*_HCAS` y los tamaños no se tocan: sin el interruptor son inertes.
- `NCCL_DEBUG_SUBSYS=INIT,NET,PROXY` (antes `INIT,NET`) en `patch-nccl-ring.yaml`, por si el anillo vuelve a colgarse.
- Comentario en `kustomization.yaml` y en los dos parches: qué es el experimento y cómo se deshace (quitar esas líneas; un revert de esta PR lo hace todo).
- Solo el overlay de la ventana: la base `k8s/glm53-tp3/` y el overlay k4 de main siguen con ARX a 1, y el render de `overlays/sparks-ventana-20261010` no cambia.

Desvío consciente de la spec: C3 de DGX-818 dice «ARX se queda como está»; este experimento lo invierte a propósito y temporalmente.

## Verificación

`.company/evidence/DGX-818-glm-sin-arx.md`: tests en rojo primero (8 fallos en el commit anterior), luego `92 passed, 1 skipped` (`tools/test_glm53_tp3_ventana.py` y `tools/test_sparks_ventana_pin.py`), y el diff del render antes/después: solo las dos variables, el `NCCL_DEBUG_SUBSYS` y el hash del ConfigMap de la receta.

No toca el cluster.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

