DGX-745: ai-lab a k8s-ai@b0d10802, S1 nvfp4 con las mejoras del residente

## Qué hace

DGX-745 S1: despliega la receta del laboratorio con las mejoras del residente, **brazo nvfp4** (KV fijo de 8 GiB con `--kv-cache-memory-bytes`, imagen `vllm/vllm-openai@sha256:fc120ece…`). Mueve `targetRevision` de `ai-lab` de `3b79a2b0…` (tras #547) al SHA de fusión de k8s-ai-pocharlies#124, `b0d10802dc0ce12ac6e24d948e08fc295a7aab57` (en `main`; su `lab/qwen38-lab.yaml` lleva `replicas: 1` y `launch-revision` `dgx745-s1-nvfp4`; trae además `lab/qwen38-lab-kernel-det.yaml` (un ConfigMap `qwen38-lab-kernel-det`)). Decisión de Dani: «despliégalo ya».

- `apps/ai-lab.yaml`: `targetRevision` y el comentario al día. `ARCHITECTURE.md`: una línea.
- Sin cambios en `tests/`: el test existente exige 40 hex y la `source` con solo `repoURL`, `targetRevision` y `path`.
- Sigue `UPS_GUARD=0` (dgx3 fuera del SAI, #122) y el vigilante de memoria activo.

## Lecturas G1 en dgx3 (solo lectura, 09-10 02:46)

- `df -h /srv`: `/dev/nvme0n1p2` 916G, 182G usados, **688G libres** (21 %).
- Marcas del vigilante en `/srv/ai-lab/cache`: solo `memwatch-tripped-mia-b7c5da1a-ckpt-ada4da32-3` y `…-4` (cortes anteriores). **No hay marca `dgx745-s1-nvfp4`**, así que el pod no saldrá con 70.
- `NV_ERR_NO_MEMORY` desde el arranque de dgx3 (08-10 20:36): **0** en `dmesg` y en `journalctl -k`.
- Memoria con el motor actual (`qwen38-lab-cbc4cbcd5`, 3 h 18 min, 0 reinicios): `MemTotal` 127535152 kB, `MemAvailable` 20862992 kB (19,9 GiB), `MemFree` 14893828 kB. Es la línea base con el motor actual encendido, no en reposo.

## Qué pasa al fusionar

`ai-lab` (`automated`, `prune`, `selfHeal`) actualiza el Deployment `qwen38-lab` (`Recreate`): el pod actual se termina (hasta 120 s) y se crea el nuevo con la receta S1; arranque de ~11 min o más. Es un cambio de receta con el motor ya encendido, no un encendido desde cero. Antes y después: `gpu-arbiter-state` (`llm-tp`, `ready`, `blockers []`), pods de `llm` con edad y 0 reinicios; después `kubectl logs -n ai-lab deploy/qwen38-lab -c vllm` (la línea `MEMWATCH: vigilante activo`) y la línea base de `NV_ERR_NO_MEMORY` (0).

## Marcha atrás, en un solo PR

PR contra `deploy/prod` que cambia **una línea** de `apps/ai-lab.yaml`:

```yaml
    targetRevision: 3b79a2b03d6093092a284a6d0355da369431e5d8
```

Es el estado anterior (receta rev -5, `replicas: 1`). El prune retira el ConfigMap `qwen38-lab-kernel-det`, que es el único objeto nuevo que añade S1. Para apagar del todo: `targetRevision` a `19a0591fb48ded74d2f116ee2b93439140247404` (`replicas: 0`); no borra el Job de la fase A ni `/srv/ai-lab`. Sin `kubectl scale`, sin `kubectl delete application`, sin tocar `lab/`.

## #548

Se cierra aparte: el apagado de la noche 1 ya no aplica (Dani dejó el lab encendido).

## Verificación

`python3 -m unittest discover -s tests -p "test_*application*.py"` → 12 OK. En k8s-ai-pocharlies: `b0d10802` es ancestro de `origin/main`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)


## Dónde se verifica cada criterio de DGX-745 (esta PR solo fija el SHA)
Esta PR de GitOps no contiene la receta: mueve `ai-lab` a `b0d10802`, la fusión de **pocharlies-org/k8s-ai-pocharlies#124**. Los criterios de código se verificaron allí:
- **C1–C8 y C12** (tabla de mejoras con origen, 8 plazas, `mode 3`/`FULL_AND_PIECEWISE`, KV 8 GiB en bytes, MTP, kernels/indexador, «no aplica» con motivo, `LAB_ARM`, tests): diff de `lab/` y `tools/test_lab_isolation_contract.py` en k8s-ai#124. Contrato 94 OK, `aprobacion/qa`, `aprobacion/architect` y `aprobacion/security` en success sobre `cd419f73`; `70-qa.md` adjunto a DGX-745 (id 23569).
- **C9–C10** (arranque sin tocar el árbitro ni `ns llm`, medición de qa): se verifican después de fusionar esta PR, que es la que enciende la receta.
- **C11** (ventana): Dani pidió desplegar ya (09-10, 02:40); dgx3 está fuera del SAI y del árbitro y no interfiere con la noche 1 del residente.
- **C13**: relación entre tickets, sin código.
