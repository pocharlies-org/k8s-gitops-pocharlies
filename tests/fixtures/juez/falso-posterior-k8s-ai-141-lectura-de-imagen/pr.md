DGX-780: Jobs del checkpoint TP=3 y tests TP=3 en ci.yml

Jira: DGX-780

Esta PR trae los Jobs sin GPU que construyen el checkpoint TP=3 en dgx3 y lo publican en dgx1 (convert, serve y publish), su ConfigMap y los tests TP=3 en `ci.yml`, con el re-pin de `tools/check_ci_security.py`. Es la última de las cuatro partes de la PR-A de DGX-780. Las otras tres, #138 (conversor), #139 (parches de arranque) y #140 (logits), ya están en `pin/qwen38-tp3-20261010`, y esta rama las integra con un merge.

## Cambios
- `k8s/qwen38fn-tp3-jobs.yaml` (nuevo) define tres Jobs: `qwen38fn-tp3-convert` en dgx3 con 16Gi, `qwen38fn-tp3-serve` en dgx3 detrás de un Service ClusterIP y `qwen38fn-tp3-publish` en nvidia-dgx con 4Gi.
  - `convert` lee la copia local del híbrido en `/srv/ai-lab/models/qwen38fn-mtp-nvidia-fp8-hybrid-7b719225` y antes de empezar le pasa `sha256sum -c`.
  - Antes de `verify` corre con TP=3 los bloques `QWEN_PLE_MMAP` y `QWEN_TP3_PLE_SHARD_SKIP` del `launch.sh` montado. Así C4(d) comprueba el loader de la imagen en el mismo estado en que arranca el motor con TP=3.
  - Borra el `verify.json` que haya quedado de una pasada anterior. La marca `.built-tp3-7b719225` solo se escribe si el `verify.json` de esta pasada trae `"pasa": true`, de modo que un OOMKill nunca acaba en PASA.
- `k8s/kustomization.yaml` añade los Jobs y el ConfigMap `qwen38fn-tp3`, plano y con `disableNameSuffixHash`.
- `.github/workflows/ci.yml` solo añade a los pasos Ruff y Unittest los seis ficheros TP=3 que ya están en la línea. `tools/check_ci_security.py` lleva el re-pin del sha256.
- `tools/test_qwen38fn_tp3_patches.py` suma `test_convert_job_patches_the_image_before_verify`, que corre ese paso del Job sobre la copia congelada de la imagen.

Head y worker no cambian, así que el residente no se reinicia. Aquí no se ha ejecutado ningún Job; eso llega con el PR-B de gitops.

## Alcance de esta PR
- C2: el Job `convert` guarda el hash del `SHA256SUMS` de TP=2, aborta si cambia y repite el `sha256sum -c` antes de dejar la marca; los shards de la tabla PLE no se reescriben
- C10: el render del overlay deja los Deployments head y worker iguales a los de `63dd55f`; el ConfigMap nuevo `qwen38fn-tp3` es plano y de nombre fijo (`disableNameSuffixHash`)
- C11: `k8s/qwen38fn-tp3-jobs.yaml` con convert (dgx3, 16Gi), serve (dgx3, ClusterIP) y publish (nvidia-dgx, 4Gi), todos sin GPU (`NVIDIA_VISIBLE_DEVICES=void`, sin `nvidia.com/gpu`), con `requests.memory == limits.memory`, sin `ttlSecondsAfterFinished` ni etiquetas `gpu.dgx-infra/*` e idempotentes por marca
- C13: solo la parte de CI: los tests TP=3 en los pasos Unittest y Ruff de `ci.yml`, con el re-pin de `tools/check_ci_security.py` (las referencias TP=2 ya están en la línea por #140)

## Cómo verificarlo
`.company/evidence/DGX-780-tp3-jobs-ci.md` recoge los pasos Ruff y Unittest de `ci.yml` sobre la rama (662 tests, OK), el render comparado con `63dd55f` y las reglas de los Jobs comprobadas sobre el render.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

