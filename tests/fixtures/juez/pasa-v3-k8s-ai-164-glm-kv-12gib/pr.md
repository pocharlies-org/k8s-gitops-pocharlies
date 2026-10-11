DGX-818: GLM TP=3 de la ventana con KV de 12 GiB y ARX de la receta

## Alcance de esta PR

- C2: modo k4 de la ventana con KV de 12 GiB y ARX de la receta

## Qué hace

Tres cambios, solo en `overlays/glm53-tp3-ventana-k4-20261010`.

ARX vuelve a ser el de la receta. Se deshace el experimento sin ARX de #163: el cuelgue del arranque era la IP del MessageQueue (`nota-sre-glm-cuelgue.md`) y el arranque de las 00:27Z, con la ruta temporal de dgx2, levantó. `VLLM_ARX_ALLREDUCE` y `VLLM_GLM_ARX_PREFETCH` salen del parche del ConfigMap `glm53-tp3-recipe`. `NCCL_DEBUG_SUBSYS=INIT,NET,PROXY` se queda porque solo añade log y ya corrió así.

`KV_CACHE_MEMORY` del modo k4 baja de 16 GiB a 12 GiB (12884901888). La compilación JIT de CUDA (`cicc`, load 121) de la primera prueba de prefix cache dejó dgx3 con MemAvailable 0 (la receta reserva 112 GiB por pod), y a las 00:34:55Z la cabeza murió con `RPC call to sample_tokens timed out`. Un rango suelto no vuelve a unirse al grupo. Con unos 4 GiB de margen por nodo se puede medir sin OOM. Quedan unos 1,8 M tokens de KV (cifra del coordinador, no medida aquí), de sobra para c≤10. Un comentario junto al literal lo explica.

El ConfigMap de modo cambia de hash (`glm53-tp3-mode-fg8mgdmbd2` a `-t5gtf2t7m5`), así que la plantilla de los tres rangos cambia y `strategy: Recreate` los reinicia a la vez, como exige la receta.

El render es el de b3f92e8 salvo el KV y el `NCCL_DEBUG_SUBSYS`. El de `overlays/sparks-ventana-20261010` no cambia (`da05b03110e0...`, el hash que midió qa).

Esta PR no arregla la IP del MessageQueue (`VLLM_HOST_IP` en el cable): tras reiniciar un nodo, dgx2 sigue necesitando su ruta temporal.

## Verificación

`.company/evidence/DGX-818-glm-kv12.md`: tests en rojo primero (`5 failed`: ARX en los tres rangos, KV de 12 GiB y la receta de la base), luego `91 passed, 1 skipped` (`tools/test_glm53_tp3_ventana.py` y `tools/test_sparks_ventana_pin.py`), `ruff check` limpio y el diff del render contra b3f92e8.

No toca el cluster.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

