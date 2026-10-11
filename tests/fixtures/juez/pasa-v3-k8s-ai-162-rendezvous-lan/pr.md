DGX-818: rendezvous y bootstrap de GLM por la LAN; mentat sigue en el triángulo

## Qué cambia

El primer arranque de GLM TP=3 en la ventana (20:41-20:52Z) murió con `DistStoreError: Timed out after 601 seconds waiting for clients. 2/3 clients joined`: los tres rangos usaron `distributed_init_method=tcp://10.0.2.3:44155` (la IP de dgx3 en su cable con dgx1) y dgx2 no la alcanza (su cable con dgx3 es 10.0.4.x). Esta PR lleva el rendezvous de vLLM y los bootstrap de NCCL y gloo por la LAN de gestión (`enP7s7`), como el TP=3 de qwen38 que sí arrancó, y deja mentat en el triángulo (S-6, DGX-811). Solo toca `overlays/glm53-tp3-ventana-k4-20261010` y su test; `k8s/` y main no cambian.

Por rango, en el contenedor `vllm`: `MENTAT_FABRIC_IP` = su IP de la LAN (dgx3 .143, dgx1 .140, dgx2 .141), `GLOO_SOCKET_IFNAME` y `NCCL_SOCKET_IFNAME` = `enP7s7`.

## DECISIÓN TOMADA: el mando es `MENTAT_FABRIC_IP`, no `VLLM_HOST_IP`

Leído antes de escribir (detalle y líneas en `.company/evidence/DGX-818-glm-lan.md`):
- La IP del rendezvous no sale de `VLLM_HOST_IP`. `RayExecutorV2` (vllm `ddd6fbca`, `ray_executor_v2.py:131/211/337`) la pide a `ray.util.get_node_ip_address()`; el shim de mentat 0.17.1 contesta `MENTAT_FABRIC_IP` y, si no, `MENTAT_NODE_IP` (la identidad del nodo, 10.0.x, que el demonio escribe en el entorno de cada rango). El agente no lee ninguna variable de dirección del motor y `ray start --node-ip-address` se ignora.
- `VLLM_HOST_IP` en la LAN, además de no mover nada, pararía la cabeza: el entrypoint de la imagen exige `VLLM_HOST_IP == HEAD_HOST` con `ROLE=head` (`entrypoint.sh:424`), y `HEAD_HOST` es el demonio de la cabeza por el triángulo (se queda).
- `MENTAT_FABRIC_IP` puesta en el contenedor es el mando que el shim documenta («the operator pinning the answer»): el agente lanza cada rango con el entorno del contenedor y el demonio solo la escribe si el grupo cae en una isla `rdma` (`mentat.env` no lleva esa etiqueta).
- Sin cambios: `MENTAT_NODE_IP`, `MENTAT_PEERS`, `HEAD_HOST`, `VLLM_HOST_IP`, `mentat.env`, el contenedor `mentatd` entero y ARX (que habla por el grupo gloo, ahora por la LAN).

## Verificación

Tests en rojo primero (`04811c5`: 6 fallos y 3 errores) y en verde (`33ece00`): `python3 tools/test_glm53_tp3_ventana.py` 26 tests OK; la lista Unittest de `ci.yml` 753 OK (skipped=57); ruff 0.12.4 y `check_ci_security.py` en verde. El render de `overlays/sparks-ventana-20261010` no cambia (`VentanaNoCambiaTest`).

No medido: que el rango herede `MENTAT_FABRIC_IP` es lectura de código (no hay `cargo` en el x86 para correr `tests/test_vllm_shape.py` de mentat). Se ve en el primer minuto de la ventana: el log de la cabeza debe decir `distributed_init_method=tcp://192.168.50.143:` y no `tcp://10.0.2.3:`. Si dice 10.0.2.3, la hipótesis cae y lo siguiente son las rutas /32 del host (dgx-infra).

Documento que lo refleja: los comentarios del overlay y la evidencia; `docs/glm-5.3-flash-tp3.md` (main) punto 2(b) de «Decisiones pendientes» se actualiza tras la ventana, no en esta PR.

## Alcance de esta PR
- C3: rendezvous y bootstrap de GLM por la LAN; mentat sigue en el triángulo

🤖 Generated with [Claude Code](https://claude.com/claude-code)

