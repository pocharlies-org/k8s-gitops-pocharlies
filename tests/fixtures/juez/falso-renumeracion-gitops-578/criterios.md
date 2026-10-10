Rol: tech-lead · Fecha: 2026-10-09 · Sesión: 5d35c318-9261-4879-b52f-24fa3c4db837 · Estado: LISTO

# DGX-781 · DGX-778 P3 · Residente qwen38 en TP=3 sobre dgx1+dgx2+dgx3 con vuelta atrás a TP=2 en un PR

## Qué y por qué
Esta historia pasa el residente de TP=2 (head en `gx10-ec3d`, worker en `nvidia-dgx`) a TP=3 + EP=3: un tercer rango en dgx3, NCCL por el triángulo CX7 y el checkpoint de DGX-780. Se prueba en una ventana con la vuelta atrás preparada antes de empezar y se mide frente a TP=2. Plan: `10-plan.md` v2; `nota-architect-plan.md` (hallazgos 5, 6 y 9; notas N3 y N4).

**Prerrequisitos** (sin ellos no se abre la ventana):
- DGX-779 PR-B desplegado (árbitro con el rango `optional` y RBAC);
- DGX-779 PR-C fusionado (`ignoreDifferences` del rango 3);
- DGX-780 fusionado en la línea pin, con `verify.json` PASA y `SHA256SUMS` en dgx1.

## Dueño, repos y ramas (un maker)
- **devops** · `k8s-ai-pocharlies`, rama `DGX-781-tp3-despliegue` desde `pin/qwen38-tp3-20261010` (con DGX-780 dentro); PR contra la línea. Cubre C1-C7. La línea pin lleva solo código y tests.
- Mismo devops · `k8s-ai-pocharlies`, base **`main`**, rama `DGX-781-architecture`. Cubre C8.
- Mismo devops · `k8s-gitops-pocharlies`, base `deploy/prod`, **dos PR abiertos a la vez**: `DGX-781-ai-tp3` (→ merge del PR de la línea pin) y `DGX-781-ai-vuelta-tp2` (→ **`63dd55f`**, el SHA completo que hoy lleva `apps/ai.yaml`; v3: ya no `fadbbdda`). Cubre C9.
- La hora la acuerda la sesión con Dani (~35-40 min de reinicio con el tráfico en Alibaba).

## Criterios de aceptación (verificables sobre el diff)
- [ ] C1 · `launch.sh`:
  - `--tensor-parallel-size 3 --nnodes 3`; EP y `allgather_reducescatter` sin cambios; `--mm-encoder-tp-mode data` (si DGX-780 C8 confirmó el soporte);
  - comprobación fail-closed de **los dos** HCA en `ACTIVE`, del mismo índice de GID RoCEv2 IPv4 en los dos y de la MTU impresa, con la salida `QWEN_TP3_PREFLIGHT ok rank=N hcas=... gid=... mtu=...`;
  - **con TP=3, los cuatro parches (`QWEN_FI_EP_UNEVEN`, `QWEN_TP3_MTP_FC_REPLICATED`, `QWEN_TP3_VOCAB_MASK` y, v4, `QWEN_TP3_PLE_SHARD_SKIP`) hacen `exit 1` si no encuentran su patrón** (hallazgo 9; los trae DGX-780: aquí se comprueba que siguen así).
- [ ] C2 · NCCL, vía A (receta de serie de bumasoft), igual en los tres rangos: `NCCL_IB_HCA==rocep1s0f0,rocep1s0f1`, `NCCL_IB_SUBNET_AWARE_ROUTING=1`, `NCCL_IB_MERGE_NICS=0`, `NCCL_CROSS_NIC=1`, `NCCL_NET=IB`, `NCCL_NET_PLUGIN=none`, y `NCCL_DEBUG=INFO` con `NCCL_DEBUG_SUBSYS=INIT,NET` solo en este arranque (con un comentario de que vuelve a `WARN`).
- [ ] C3 · Plano de control por la LAN de gestión: `VLLM_MASTER_ADDR=192.168.50.141`; `VLLM_HOST_IP` = `.140`, `.141` o `.143` según el nodo; los `*_SOCKET_IFNAME` = el netdev LAN de cada nodo (la entrega dice cómo se leyó). No queda ninguna `10.0.0.x` como dirección de control.
- [ ] C4 · Deployment `qwen38-flash-next-worker-dgx3`, copia del worker con estas diferencias y ninguna más: nombre, `dgx3` con la tolerancia `dedicated=llm:NoSchedule`, `VLLM_NODE_RANK=2`, `VLLM_HOST_IP` y los `*_SOCKET_IFNAME`, `GPU_MEM_UTIL` de puerta y el PVC nuevo. `--headless` y `replicas: 1` en git.
- [ ] C5 · `k8s/hf-cache-dgx1-dgx3-llm-nfs.yaml`: PV + PVC en `llm`, `ReadOnlyMany`, `Retain`, NFS `10.0.2.1:/home/dibanerz/.cache/huggingface` con `ro, vers=3, proto=rdma, port=20049, hard`. Un comentario explica que `hf-cache-nvidia-dgx-ro` va por la IP 10.0.0.x de la malla del TP, que dgx3 no alcanza. Se añade a `k8s/kustomization.yaml`.
- [ ] C6 · En los tres Deployments:
  - `MODEL_PATH=/cache/huggingface/qwen38fn-mtp-nvidia-fp8-hybrid-tp3`;
  - `KV_CACHE_MEMORY_BYTES=51539607552` (48 GiB; v4, C-3). Lleva un comentario con la cuenta de la fórmula «Tope del KV» de `docs/qwen38-flash-next-ple-nvme-20261009.md` (manda el head `gx10-ec3d`, mínimo de 3 días 1,27 GiB, reserva de 4,0 GiB para la caché de la tabla, ≥ 5 GiB libres por nodo según la regla de Dani):
    - tope TP=2 37,1 GiB, más ~11,5 de pesos por rango = ~48,6 GiB; se toman 48;
    - `MemAvailable` mínimo estimado: head ~5,6 GiB, worker ~10,8 GiB;
    - 2 cabezas KV por rango, ~3,36 M tokens frente a los 5,04 M de `63dd55f` (~0,67×). La capacidad la decide vLLM con el estado GDN dentro del pool;
    - puerta en 3,19 M tokens; la cifra la mide este arranque;
  - el mismo `launch-revision` nuevo (`vllm-qwen38fn-20261010-tp3`).

  `SPECULATIVE_CONFIG` como en `63dd55f`.
- [ ] C6b (v3) · La PLE en el NVMe a tp=3, en los tres Deployments:
  - initContainer `ple-table` (el de `63dd55f`) con `TP_SIZE=3`, `TP_RANK` 0, 1 o 2 y `CKPT_DIR=/cache/huggingface/qwen38fn-mtp-nvidia-fp8-hybrid-tp3`;
  - hostPath `ple-table` (`/home/dibanez/.cache/qwen38fn-ple`, `DirectoryOrCreate`);
  - ConfigMap `qwen38fn-ple-mmap` y `QWEN_PLE_MMAP_DIR=/ple`.

  En `qwen38-flash-next-worker-dgx3` también, porque es copia del worker de `63dd55f`.
- [ ] C7 · `tools/test_qwen38fn_tp3_manifest.py` comprueba:
  - rangos 0/1/2 en `gx10-ec3d`, `nvidia-dgx` y `dgx3`;
  - paridad de `env`, `args`, `volumeMounts` y `resources` salvo una lista blanca escrita;
  - `NCCL_IB_HCA` de cada nodo según la copia congelada de `ring.conf` en `tools/fixtures/`, con cabecera del commit de dgx-infra (`8da5d84b` o el vigente) y su sha256. En dgx1 y dgx2, `rocep1s0f0` se deriva del netdev `enp1s0f0np0` de las filas `tp` (N4);
  - nada de `10.0.0.x` en el plano de control;
  - TP 3, nnodes 3 y `--mm-encoder-tp-mode data`;
  - el `exit 1` de los **cuatro** parches con TP=3 y sin patrón (`test_tp3_patches_fail_closed`, `QWEN_TP3_PLE_SHARD_SKIP` incluido), con la fixture del fichero de la imagen;
  - (v3) en los tres Deployments, initContainer `ple-table` con `TP_SIZE=3` y `TP_RANK` igual a `VLLM_NODE_RANK`, `CKPT_DIR` de la vista TP=3 y `QWEN_PLE_MMAP_DIR`. `tools/test_qwen38_flashinfer_contract.py` sigue en verde.

  Entra en Unittest y Ruff de `ci.yml`, con el re-pin de `check_ci_security.py`.
- [ ] C8 (PR contra `main`; hallazgo 5) · `ARCHITECTURE.md`:
  - §1, la topología TP=3 y la línea `pin/qwen38-tp3-20261010`;
  - §6, `test_qwen38fn_tp3_manifest.py`;
  - §8, NCCL en triángulo, plano de control por la LAN, el PV de dgx3, la puerta de 0,85× y la vuelta atrás.

  La línea pin no lleva el documento.
- [ ] C9 · Los dos PR de gitops tocan solo `apps/ai.yaml`; sus comentarios se citan entre sí. El de vuelta atrás dice:
  - que `prune: true` retira el rango 3 y el PV/PVC sin borrar datos;
  - **cómo se ejecuta tras el otro merge** (N3): `git fetch origin && git merge origin/deploy/prod` en su rama, resolver el conflicto de `targetRevision` a `63dd55f…`, hacer push y esperar el nuevo veredicto del juez. Al volver, la tabla PLE se reconstruye sola a tp=2 (`ready.json` con `tp_size=3` no casa), ~42 s por nodo.
- [ ] C10 (v3, nota de qa sobre DGX-779) · Antes de la ventana, la entrega cita con fichero:línea `_component_profiles` en `dgx-infra/services/dashboard/routes_service_health.py` y `PROFILE_LOCAL_LLM_SERVER_IDS` en `compute_mode.py`, que leen `COMPONENTS` sin filtrar por presencia, y comprueba `GET /api/service-health` y `GET /api/compute/mode` con el rango de dgx3 **ausente** (hoy) y **presente** (en la ventana):
  - si ninguno marca degradado ni rompe el enrutado local, se deja escrito;
  - si alguno lo hace, se abre un Bug en DGX con la evidencia, enlazado a DGX-779, y no se abre la ventana hasta que esté arreglado (no se arregla en esta historia: el código es de dgx-infra).

## Test que debe fallar primero
`python -m unittest tools/test_qwen38fn_tp3_manifest.py` en `pin/qwen38-tp3-20261010` (dos Deployments, TP=2, `NCCL_IB_HCA==rocep1s0f0`, master `10.0.0.2`): falla, y pasa en la rama. Tests: `test_three_ranks_on_three_sparks`, `test_rank_parity_except_allowlist`, `test_nccl_hcas_match_ring_conf`, `test_control_plane_off_the_mesh` y `test_tp3_patches_fail_closed`. La entrega pega las dos salidas.

## Referencias
- `pin/qwen38-tp3-20261010:k8s/qwen38-flash-next-nvfp4-vllm.yaml` (= `63dd55f` + DGX-780; las líneas se desplazan, búscalas por nombre; el initContainer `ple-table` y el bloque `QWEN_PLE_MMAP` vienen de `63dd55f`):
  - `launch.sh`: RDMA en 3036-3049, TP en 3061, nnodes/rank/master en 3083-3086, KV en 3111-3134, `--headless` en 3205-3215;
  - head: `VLLM_MASTER_ADDR` en 3413, `MODEL_PATH` en 3438, `GPU_MEM_UTIL` en 3474, KV en 3500, `SPECULATIVE_CONFIG` en 3766, NCCL en 3850-3895;
  - worker: 4033-4729.
- `dgx-infra` `origin/master:scripts/roce-link/ring.conf`.
- `origin/main:lab/hf-cache-dgx1-lab-nfs.yaml`.
- `k8s/llm-deploy-hooks-jobs.yaml`.
- `k8s-gitops-pocharlies` `apps/ai.yaml` 1560-1600 y `kustomization.yaml` 262-275 (lo trae DGX-779 PR-C).
- Receta NCCL de bumasoft (MIT), bloque `NCCL_COMMON` de `serve.sh` (rama `master`).
- Vía B: el NCCL parcheado de Staticduo (`staticduo14-tp3-marlin-20261008.tar.gz`, sha256 `5595d85c725b7341b08fa7bd6e878630d34283f876afaf710e27c015d1e1200e`, mensajes 3497/3500/3503 del tema 117), solo con licencia escrita; si no la hay, `ESTADO: BLOQUEO` y vuelta a TP=2.
- `tools/qwen38_decode_sweep.py` (**solo en `main`: se ejecuta desde un checkout de `main`**), `tools/qwen38_smoke.py` y `tools/qwen38_tp_logits_compare.py`, más las consultas de VictoriaMetrics de DGX-777.
- **No construir**: perfil de cómputo, NCCL propio de entrada, cambios en el MTP, `kubectl scale` o `apply` a mano, `ARCHITECTURE.md` en la línea pin.

## Efecto observable (tras fusionar `DGX-781-ai-tp3`; lo comprueba la sesión, no la puerta de la PR)
Ventana de 2 h como máximo desde que el head está Ready:
- `ai` Synced y Healthy en el merge; los tres pods `Running`; `/health` 200;
- en cada rango, `QWEN_TP3_PREFLIGHT ok`, `QWEN_FI_EP_UNEVEN (aplicado|ya aplicado)` y `QWEN_FI_EP_UNEVEN activo (E=512, ep=3, rank=N)`, y NCCL `via NET/IB`;
- `QWEN_PLE_TABLE construida` con `tp_size 3` y `QWEN_PLE_MMAP aplicado` en cada rango;
- **`GPU KV cache size` ≥ 3,19 M tokens** (v4, C-4: 95 % de la estimación de 3,36 M con 48 GiB, y nunca por debajo de los 2,94 M con los que vivió producción hasta las 19:29Z; la capacidad la decide vLLM con el estado GDN) y `MemAvailable` ≥ 4 GiB en los tres nodos;
- logits T1-T5 PASA contra `ref-tp2-63dd55f-A.json` con el suelo de B; smoke PASA; aceptación MTP a ≤ 0,05 de la de `63dd55f`;
- las medidas de la sonda de `main` (abajo) contra TP=3, más VictoriaMetrics ≥ 60 min con tráfico real.

**Medida (v4, C-5)**, con `tools/qwen38_decode_sweep.py` desde un checkout de **`main`**, los mismos comandos en los dos lados. `--compare` no sirve: compara salidas de `--quality`, no tok/s.
- **Agregado**: `--concurrency 1,4,8,10 --reps 3 --out …`. Por concurrencia se compara la **mediana de los puntos con `contaminado: false`**. Un punto contaminado se repite con el tráfico apartado (LiteLLM a Alibaba durante la medida o fuera de horas); nunca se usa.
- **64k**: `--concurrency 8 --long-workers 8 --long-tokens 64000` y `--concurrency 10 --long-workers 10 --long-tokens 64000`, todo largo y en frío. Si la sonda rechaza `long-workers` igual a los hilos (`qwen38_decode_sweep.py:323`), se define un modo mixto (por ejemplo `--long-workers 4`) y se usa **el mismo** en las dos bases. La entrega dice cuál.
- **Térmica**: `--thermal-url` (VictoriaMetrics) y un `--thermal-query` que incluya `dgx3` además de `nvidia-dgx` y `gx10-ec3d`. La etiqueta de nodo se lee de la métrica antes de escribir la consulta.

**Base de comparación: TP=2 en `63dd55f`, remedida el mismo día antes de la ventana** con esos comandos (`--reps 3`). La medida de k8s-4d (28,8 / 102,4 / 148,3 tok/s en c1/c4/c8, una sola pasada) queda como referencia. La entrega escribe la **dispersión entre repeticiones** de cada punto: si pasa del 2,5 %, los umbrales del ±5 % de ese punto pasan a **2 × la dispersión** (igual que T4).

**Regla de decisión, frente a la remedición de `63dd55f`.** Se ejecuta la vuelta atrás (probada) si:
- falla cualquier punto de arriba;
- el agregado cae más del umbral en c4 o en c8 (con la base de k8s-4d y ±5 %: < 97,3 o < 140,9 tok/s);
- el 64k en c8/c10 cae > 10 %;
- el tok/s por petición con 7-10 peticiones (VictoriaMetrics) baja > 5 %;
- **o TP=3 no gana**: no sube más del umbral ni en c8 (con la base de k8s-4d, ≥ 155,7 tok/s) ni en c4 (≥ 107,5). Con ~33 % menos de KV que `63dd55f` y dgx3 ocupado, una mejora menor no compensa.

Si no se da ninguna, TP=3 se queda y la vuelta atrás queda abierta y enlazada (documentada). La tabla `63dd55f` frente a TP=3 va en la entrega.

## Fuera de alcance
P/D separado (DGX-688/690), cambiar el MTP (DGX-777), la PLE en NVMe (DGX-773), el medio B de los enlaces, las rutas /32 y encender el lab.
