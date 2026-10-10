DGX-781: vuelta atrás a TP=2 (ai de 1f5aefd a a51da60)

Jira: DGX-781

## Alcance de esta PR
- C9: PR de vuelta atrás a TP=2 de la ventana TP=3. Toca solo `apps/ai.yaml`: `targetRevision` de `ai` de `1f5aefd` a `a51da60`, con el comentario de vuelta.

## Qué es
La ventana decide VOLVER a TP=2: el residente está caído. Dos arranques TP=3 fallaron en NCCL (`ibv_modify_qp` 110: dgx2 `rocep1s0f0` -> GID 10.0.2.3 de dgx3, entre carriles), incluso con `NCCL_IB_SUBNET_AWARE_ROUTING=1` y `NCCL_IB_SUBNET_PREFIX_LEN=24`.

`deploy/prod` tiene `ai` en `1f5aefd88e6c2660a7b4d05152444541e836531d` (tras #577 y #579). Esta rama, ya fusionada con `origin/deploy/prod`, lo deja en `a51da6025a7fe175549a349e0c4400959f602ae9` (el TP=2 vivo antes de la ventana; head y worker iguales que 63dd55f). Diff contra el tronco: 1 fichero, `-1`/`+8` líneas, el `targetRevision` y su comentario; `syncPolicy` sin tocar.

## Qué cambia al volver
Render de `overlays/ornith-sm121v5-lmheadw4-20260721` (medido en la versión anterior de esta PR, `47c8ff2` -> `a51da60`; `1f5aefd` solo añade `NCCL_IB_SUBNET_PREFIX_LEN=24`):
- Desaparecen: Deployment `qwen38-flash-next-worker-dgx3`, PV `hf-cache-dgx1-dgx3-llm-ro` y PVC `llm/hf-cache-dgx1-dgx3-llm-ro`.
- Cambian: Deployments `qwen38-flash-next-head` y `qwen38-flash-next-worker`, y el ConfigMap `qwen38-flash-next-vllm-launch`. Head y worker se reinician: unos 33 min, con el tráfico en Alibaba.
- La tabla PLE se reconstruye sola a tp=2 (el `ready.json` con `tp_size=3` no casa), unos 42 s por nodo.

## Recursos que quedan huérfanos si la app no poda
La app `ai` tiene `prune: true` y `selfHeal: true`: la sync de esta PR poda el worker-dgx3 y el PV/PVC. El PV es `Retain` y el NFS es de solo lectura: no se borra ningún dato.

Si la app pasa a `prune: false`, quedan huérfanos el Deployment `qwen38-flash-next-worker-dgx3` (con su pod en dgx3), el PV y el PVC. Se retiran con una sync acotada a esos tres recursos (`operation.sync.prune: true` más `resources`, `ARCHITECTURE.md` §5), sin borrar nada a mano.

El árbitro (`dgx-infra` `services/dashboard/compute_mode.py`, lectura del código, no prueba en vivo): tolera el worker-dgx3 ausente (DGX-779), pero un worker-dgx3 presente y huérfano cuenta como componente obligatorio de `llm-tp`, no llega a Ready con un head TP=2 y la transición acaba en `phase: error`. Si la app no poda, hay que retirarlo antes de reabrir tráfico.

## Verificación
- `python3 -m unittest discover -s tests -p 'test_*.py'`: 69 tests OK. `apps/ai.yaml` parsea como YAML.
- `git diff origin/deploy/prod`: solo `apps/ai.yaml`.
- Documento que refleja el cambio: el comentario de `apps/ai.yaml`. El `ARCHITECTURE.md` de este repo no necesita cambio.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

