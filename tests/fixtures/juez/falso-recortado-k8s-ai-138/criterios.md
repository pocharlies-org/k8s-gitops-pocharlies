Rol: tech-lead · Fecha: 2026-10-09 · Sesión: 5d35c318-9261-4879-b52f-24fa3c4db837 · Estado: LISTO

# DGX-780 · DGX-778 P2 · Checkpoint TP=3 del híbrido 7b719225, parches inertes en TP=2 y referencia de logits TP=2

## Qué y por qué
El residente sirve `qwen38fn-mtp-nvidia-fp8-hybrid` (rev `7b719225242aacd3dbd3f9407468c2ee9a9d2594`). Con TP=3 no dividen por 3:
- KV 2;
- GDN 16:48;
- shared expert 640;
- el vocabulario 248320;
- quizá el `padded_vocab_size` de la PLE.

`hidden_size` 2560 rompe además las FC del MTP. Esta historia deja tres cosas:
- un checkpoint derivado y exacto por construcción, sin tocar el de TP=2, validado contra los **cargadores reales** de la imagen con tp=3;
- los parches de arranque, inertes en TP=2 y fail-closed en TP=3;
- la herramienta de logits con la referencia TP=2 capturada.

Plan: `10-plan.md` v2 de DGX-778; `nota-architect-plan.md` (hallazgos 5, 7, 8 y 9; notas N1, N2, N5 y N9).

**Cambio de base (v3).** DGX-773 está en producción: `ai` va en **`63dd55f`**, que es `fadbbdda` más la tabla PLE en el NVMe de cada nodo (`ple_mmap.py`, `build_ple_table.py`, initContainer `ple-table`, KV de 36 GiB). La línea `pin/qwen38-tp3-20261010` ya está en `63dd55f` por un fast-forward. **La tabla PLE no va a la GPU ni se reescribe en el checkpoint.**

## Dueños, repos y ramas (tres PR, dos makers)
- **PR-A · developer** · `k8s-ai-pocharlies`.
  - La línea `pin/qwen38-tp3-20261010` ya existe y está en `63dd55f`.
  - La rama `DGX-780-tp3-checkpoint` (que sale de `fadbbdda`) **integra la base con `git fetch origin && git merge origin/pin/qwen38-tp3-20261010`, nunca con rebase**, y resuelve el conflicto de `launch.sh` dejando **los dos** bloques: `QWEN_PLE_MMAP` de `63dd55f` y los parches TP=3 de esta historia, cada uno con su marcador.
  - PR **contra `pin/qwen38-tp3-20261010`**. Cubre C1-C12 y C15. La línea pin lleva solo código y tests.
- **PR-D · developer** (el mismo) · `k8s-ai-pocharlies`, base **`main`**, rama `DGX-780-architecture`. Cubre C13.
- **PR-B · devops** · `k8s-gitops-pocharlies`, base `deploy/prod`, rama `DGX-780-ai-pin-jobs`. Cubre C14. **Solo con el lab ya apagado (DGX-779 PR-A en producción).**

## Criterios de aceptación (verificables sobre el diff)
- [ ] C1 · Conversor `k8s/qwen38fn-tp3/convert.py` (se ejecuta con `python3 -I`, con torch y safetensors de la imagen):
  1. **Al arrancar** comprueba el `config.json` de origen y aborta si alguna cifra no casa: 24 q / 2 kv / `head_dim` 256; GDN 16:48 de dim 128 con conv 4; shared 640; 512 expertos con `moe_intermediate` 640; vocab 248320; `hidden` 2560; PLE `ngram_size` 3, 8 heads, `split_ngram_parts` 128, `ple_layer_ids` [2].
  2. **Escribe la vista TP=3**:
     - KV 2 → 6 (`[k0,k0,k0,k1,k1,k1]` en `k_proj`/`v_proj` y sus normas) en las 12 capas full y en el MTP;
     - GDN 16/48 → 24/72, con cabezas a cero y reparto 6/5/5; cada grupo (1 k + 3 v) viaja junto en `in_proj_qkvz`, `in_proj_ba`, `conv1d`, `A_log`, `dt_bias` y las columnas de `out_proj`;
     - shared 640 → 768 con ceros (gate y up por separado, columnas de down), también en el MTP;
     - `embed_tokens` y `lm_head` a 248448 filas con las nuevas a cero, y **`config.vocab_size` 248448**. El tokenizador no cambia (sigue con 248320 ids) y la entrega lo dice;
     - escalas FP8 por bloques movidas o duplicadas con su bloque: en el relleno, peso 0 y escala 1.
  3. **PLE (v3)**: la tabla **no se reescribe ni se rellena en el checkpoint**. Sus shards quedan como enlaces relativos a la vista hermana. El conversor:
     - calcula `padded_vocab_size` como **`ceil(total_filas_del_checkpoint / 384) · 384`** con el divisor del `config.json` TP=3 (v4, C-1). No duplica la lógica de primos de la imagen: vale porque 384 es múltiplo del 128 anterior. El total de filas sale de las cabeceras de los shards;
     - si el `padded_vocab_size` con 128 no es múltiplo de 3 (la cuenta del tech-lead da 320.001.536, resto 2), sube **solo en el `config.json` de la vista TP=3** `make_ngram_vocab_size_divisible_by` a 384, lo que da 320.001.792 filas, 256 de relleno;
     - C4(c) afirma que ese valor es igual al `padded_vocab_size` de la clase real.

     La entrega da las cifras reales. Se quita del conversor cualquier código que recorte o rellene shards de la PLE. **v4: con solo el divisor, el motor no arranca**: `ngram_embedding.py:908-921` exige 2.500.014 filas por shard y el checkpoint trae 2.500.012. Lo resuelve el parche C7b; los shards no se tocan.
- [ ] C2 · Expertos enrutados, shards de la tabla PLE y ficheros sin tensores modificados: enlaces relativos a la vista hermana. El Job informa de cuántos GiB reescribe. Si un tensor modificado comparte shard con expertos, se reescribe el shard entero y la entrega lo dice (N2). Ningún byte del directorio de TP=2 cambia: el Job compara su `SHA256SUMS` antes y después.
- [ ] C3 · `tools/test_qwen38fn_tp3_convert.py`: tensores sintéticos con las proporciones reales; suma de parciales de TP=2 frente a TP=3 en fp32 en CPU para atención, GDN, shared, embedding y PLE. Error ≤ 1e-5 y relleno a 0 exacto.
- [ ] C4 · `verify.json` del Job `convert`, en cuatro partes:
  - **(a) equivalencia en tensores reales**: capas 0 (GDN) y 3 (full) y shared de la capa 0, decuantizados en CPU, iguales bit a bit en lo real, 0 en el relleno y escalas iguales por bloque;
  - **(b) `verify-loaders`**: sin GPU y con `tensor_model_parallel_world_size=3`, para cada rango 0, 1 y 2 instancia en CPU las capas **reales de la imagen** (GDN de la capa 0, full de la capa 3, shared de la capa 0, `VocabParallelEmbedding`/`ParallelLMHead`) y carga los tensores convertidos con su `weight_loader`. Exige que lo real sea igual al original y el relleno sea 0 en cada rango. **v3: se quita la ventana PLE** (cargar bytes de la tabla y compararlos), porque la tabla no se carga en la GPU.
  - **(c) rangos PLE (v3, sustituye a `ngram_embedding` en (b))**: para los rangos 0-2 con tp=3, los `shard_indices.org_vocab_start_index/org_vocab_end_index` de la clase real de la imagen, con el `config.json` de la vista TP=3, tienen que ser iguales a `row_start/row_end` de `build_ple_table.plan(tp_size=3, tp_rank=r)`. Es el contrato que `ple_mmap.py:69-79` comprueba contra `ready.json` al arrancar. **v4 (C-2)**: los rangos se obtienen con la función estática de índices de `VocabParallelEmbedding` de la imagen (o en el dispositivo `meta`), **nunca instanciando la tabla**: el Job tiene 16Gi y un rango son ~15,9 GiB.
  - **(d) chequeo de forma de los shards PLE (v4)**: reproduce el de `ngram_embedding.py:908-921` (`shard_size = ceil(org_vocab_size / split_ngram_parts)`, `expected_rows = min(shard_size, org_vocab_size − i·shard_size)`) contra las **cabeceras** safetensors y el `config.json` de la vista TP=3, con `QWEN_TP3_PLE_SHARD_SKIP` aplicado al fichero de la imagen. Solo cabeceras: ni bytes ni memoria. Sin el parche falla (`Shape mismatch` en el shard 0); con él pasa porque los shards se saltan.

  `"pasa": true` solo si (a), (b), (c) y (d) pasan.
- [ ] C5 · `QWEN_FI_EP_UNEVEN` portado de `929b59e` (bloque, `tools/test_qwen38fn_fi_ep_uneven.py` y fixture) **con un cambio** (hallazgo 9): con `tp_size % 3 == 0` (o `E % ep != 0`), `AVISO: patron no encontrado` pasa a `exit 1`. Con TP=2 es inerte, y el test prueba byte a byte que con `E % ep == 0` el fichero de la imagen no cambia.
- [ ] C6 · Parche `QWEN_TP3_MTP_FC_REPLICATED`: `fc_embedding` y `fc_hidden` de `models/qwen4_exp/nvidia/mtp.py` pasan a `ReplicatedLinear` solo con `tp_size % 3 == 0`. Idempotente por marcador; con TP=3 y sin patrón, `exit 1`; con TP=2, inerte.
- [ ] C7 · Parche `QWEN_TP3_VOCAB_MASK` (hallazgo 7), mismo mecanismo que C6: con `config.vocab_size` > número de ids del tokenizador, pone `-inf` a los logits ≥ 248320 **antes del muestreo y de `prompt_logprobs`**. Lleva test sobre una copia congelada del fichero de la imagen. Con TP=2 (vocab 248320), inerte.
- [ ] C7b (v4, arreglo A del architect) · Parche `QWEN_TP3_PLE_SHARD_SKIP`, mismo mecanismo que C6/C7: dentro de `Qwen4ExpNGramEmbedding.load_weights` de la imagen (`vllm/models/qwen4_exp/nvidia/ngram_embedding.py`, ~900), con `QWEN_PLE_MMAP_DIR` puesto y `tp_size % 3 == 0`, los tensores `ngram_embedding.shard_<i>.weight` hacen `continue` **antes** del chequeo de forma de 908-921 (sus filas ya salen del NVMe por `ple_mmap.py`). La escala global FP8 de la tabla se sigue cargando. Idempotente por marcador. Si el ancla no casa exactamente una vez con TP=3, `exit 1`; con TP=2, inerte (el fichero de la imagen no cambia ni un byte). Va con su test sobre el fixture `tools/fixtures/qwen38_resident_96b234af/…ngram_embedding.py` de `63dd55f`. `build_ple_table` sigue leyendo los shards sin tocar.
- [ ] C8 · Lectura de la imagen (`96b234af…`) con fichero:línea en la entrega (N1). Cubre:
  - indexer QSA replicado (4 cabezas);
  - `mm_encoder_tp_mode`/`use_data_parallel` en la clase de visión;
  - `fused_qk_norm_rope_gate` con 8 q / 2 kv por rango;
  - el loader FP8 por bloques (vllm#47005);
  - el dial de refusal con `world_size=3`.

  Cualquier parche que salga de ahí sigue las reglas de C6. Si no hace falta ninguno, la entrega dice por qué.
- [ ] C9 · **El PR-A no reinicia el residente**: `kustomize build overlays/ornith-sm121v5-lmheadw4-20260721` del PR y de **`63dd55f`** (la base nueva), filtrado a los Deployments head y worker (initContainer `ple-table` incluido), da `diff` vacío. `tools/test_qwen38_flashinfer_contract.py` de `63dd55f` sigue en verde junto a los tests de esta historia. Los ConfigMaps nuevos son **planos, con nombre fijo** (patrón de `qwen38-flash-next-vllm-ple`; N5).
- [ ] C10 · Jobs en `k8s/qwen38fn-tp3-jobs.yaml`. Todos: sin GPU (`NVIDIA_VISIBLE_DEVICES=void`, sin `nvidia.com/gpu`), `requests.memory == limits.memory`, sin `ttlSecondsAfterFinished` y sin etiquetas `gpu.dgx-infra/role|workload`.
  - **convert** (dgx3, 16Gi): comprueba el `SHA256SUMS` de la copia local de solo lectura, exige espacio ≥ 1,2× lo que escribe, convierte, corre C4 y deja `.built-tp3-7b719225` solo con `verify.json` PASA.
  - **serve** (dgx3): HTTP de solo lectura detrás de un Service ClusterIP.
  - **publish** (`nvidia-dgx`, 4Gi): **comprueba el espacio libre en dgx1**, trae los ficheros reescritos **por la red del CNI** (no es el enlace CX7; N2), crea los enlaces relativos, hace `sha256sum -c` de la vista entera y renombra de forma atómica a `/home/dibanerz/.cache/huggingface/qwen38fn-mtp-nvidia-fp8-hybrid-tp3`.
  - Idempotentes por marca.
- [ ] C11 · `tools/qwen38_tp_logits_compare.py` con el fixture de 40 prompts (≥ 8.000 posiciones), modos `capture` y `compare`, y T1-T5 con los umbrales de `10-plan.md`. T5 **prueba el parche C7**. `tools/test_qwen38_tp_logits_compare.py` usa JSON sintéticos:
  - idéntico → PASA;
  - una cabeza cambiada → falla por T3;
  - un id 248400 → falla por T5.

  Incluye el plan B si el motor rechaza `prompt_logprobs`.
- [ ] C12 · Referencias TP=2 capturadas contra **`63dd55f`** vivo (la PLE ahora se lee del NVMe): `ref-tp2-63dd55f-A.json` y `-B.json`, con el suelo A frente a B en la entrega. Las de `fadbbdda`, si ya existen, se quitan. Tests nuevos en Unittest y Ruff de `ci.yml`, con el re-pin de `tools/check_ci_security.py`.
- [ ] C13 (PR-D, contra `main`; hallazgo 5) · `ARCHITECTURE.md`:
  - §6 con los tests nuevos y su comando;
  - §8 con la línea `pin/qwen38-tp3-20261010` (qué lleva y que la verdad del documento es `main`), el checkpoint TP=3 (ruta, `SHA256SUMS`, cómo se regenera) y los **cuatro** parches TP=3 (`QWEN_FI_EP_UNEVEN` con `exit 1`, `QWEN_TP3_MTP_FC_REPLICATED`, `QWEN_TP3_VOCAB_MASK` y `QWEN_TP3_PLE_SHARD_SKIP`);
  - **el pin vivo de `ai` corregido de `d017c92` a `63dd55f`**, con la fecha de «Última verificación»;
  - la nota de §8 que dice que el residente no puede usar el offload de la PLE con 2 nodos, reescrita (DGX-773 la dejó falsa);
  - `build_ple_table.py` a tp=3.
- [ ] C15 (v3) · `k8s/qwen38-flash-next-ple-mmap/build_ple_table.py` acepta `TP_SIZE=3`:
  - `padded_vocab_size` = `ceil(total / divisor) · divisor`, con el divisor del `config.json` de `CKPT_DIR` (C-1; el script es solo stdlib y no reimplementa los primos);
  - los rangos de fila por rango salen con la misma fórmula que `VocabParallelEmbedding` de la imagen sobre ese `padded_vocab_size` (`[r·p, (r+1)·p)` con `p = padded / 3 = 106.667.264`), y no con `total // tp_size`;
  - las filas que no están en el checkpoint (las 256 de relleno) se escriben a cero;
  - `ready.json` lleva `tp_size` 3 y los `row_start`/`row_end` que `ple_mmap.py` exige.

  Con `TP_SIZE=2` el resultado es **byte a byte** el de `63dd55f` (mismo `sha256`). El test va en `tools/test_qwen38_flashinfer_contract.py` o en el de conversión, sobre un checkpoint sintético con un número de filas no divisible por 3.
- [ ] C14 (PR-B) · `apps/ai.yaml` `targetRevision` = merge de PR-A, con un comentario (no reinicia el residente; voz 2-3 min; ROLLBACK `63dd55f…`). Único fichero y el YAML parsea.

## Test que debe fallar primero
`python -m unittest tools/test_qwen38fn_tp3_convert.py tools/test_qwen38fn_tp3_patches.py tools/test_qwen38_tp_logits_compare.py tools/test_qwen38fn_fi_ep_uneven.py` en `pin/qwen38-tp3-20261010` recién creada: falla, y pasa en la rama.

Como «el módulo no existe» no es un rojo de comportamiento (N9), la entrega pega además, para cada test de conversión, el fallo con un **conversor roto a propósito**:
- una escala sin mover → falla `test_fp8_block_scales_follow_their_blocks`;
- el relleno sin ceros → falla `test_gdn_padding_is_exact`;
- KV sin triplicar → falla `test_kv_heads_duplicated_tp3_matches_tp2`.

Para los parches:
- `test_ep_uneven_exit_on_missing_pattern_tp3`;
- `test_vocab_mask_neg_inf_above_248320`;
- `test_mtp_fc_replicated_only_tp3`;
- `test_ple_shard_skip_only_tp3_with_mmap` (v4);
- `test_tp3_patches_fail_closed`: los **cuatro** parches hacen `exit 1` con TP=3 y sin ancla (v4);
- `test_tp3_view_ple_shard_shapes_pass_image_loader` (v4, C4d): rojo con la vista TP=3 sin el parche y verde con él;
- `test_patches_inert_tp2_byte_identical`: los cuatro.

## Referencias
- `fadbbdda:k8s/qwen38-flash-next-nvfp4-vllm.yaml`: PLE `padded_vocab_size` en 275-332, `copy_ple_embedding_shard_` en 540-566, `key_proj`/`value_proj` replicados en ~612-625, ConfigMap del launch en 3027-3335, `MODEL_PATH` en 3438/4129, hostPath del worker en 4696-4705.
- `929b59e`: el bloque, el test y la fixture de `QWEN_FI_EP_UNEVEN`.
- `origin/main:lab/qwen38-lab-prepare-hybrid.yaml` (patrón del Job) y `origin/main:ARCHITECTURE.md` §6 y §8.
- `fadbbdda:k8s/qwen38-flash-next-ursucipian-mod/overlays/qsa.py` 285-325, `refusal/payload/refusal_projection.py` 240-275 e `install.py` 64.
- `fadbbdda:k8s/llm-deploy-hooks-jobs.yaml` 1-50.
- Comunidad, como referencia: bumasoft (MIT), `pad_tp3.py`/`tp3_patch.py`/`ple_patch.py`. Staticduo: no se toca sin licencia.
- `63dd55f:k8s/qwen38-flash-next-ple-mmap/build_ple_table.py` (41-90 `plan`, 80-81 la división que hoy falla con 3) y `ple_mmap.py` (69-79, la marca por rango); el bloque `QWEN_PLE_MMAP` de `launch.sh`; `tools/test_qwen38_flashinfer_contract.py`; la entrega de DGX-773 (160.000.768 filas × 160 B por rango).
- **No construir**: recuantización, reescritura o relleno de la tabla PLE en el checkpoint, la ventana PLE de `verify-loaders`, un rebase de la rama, `configMapGenerator` con hash, `ARCHITECTURE.md` en la línea pin, cambios en los Deployments head y worker.

## Efecto observable (tras el PR-B; lo comprueba la sesión, no la puerta de la PR)
- Jobs convert y publish `Complete`; `verify.json` con `"pasa": true` (equivalencia, `verify-loaders` y rangos PLE en los rangos 0-2).
- En dgx1, `…/qwen38fn-mtp-nvidia-fp8-hybrid-tp3/SHA256SUMS` con `sha256sum -c` OK; el `SHA256SUMS` de TP=2 no cambia.
- Head y worker sin reiniciar; `ai` Synced y Healthy.
- `ARCHITECTURE.md` de `main` dice `63dd55f` como pin vivo.

## Fuera de alcance
DGX-781 (despliegue), cambiar el MTP (DGX-777), la PLE en NVMe (DGX-773), llevar la línea pin a `main`.
