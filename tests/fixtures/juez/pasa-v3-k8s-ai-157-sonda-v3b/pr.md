DGX-810: sonda NCCL v3b (subPath del volumen image; Jobs v3b y v3 fuera del render)

La sonda v3 (#156) falló en los tres Sparks antes de empezar: `can't open file '/opt/nccl-ring/nccl_ring_graph.py'`. El volumen `image` monta la raíz de la imagen y los COPY de `images/nccl-ring/Dockerfile` (main, líneas 59-61) dejan los ficheros en `/opt/nccl-ring/` de esa raíz, así que con `mountPath: /opt/nccl-ring` quedaban en `/opt/nccl-ring/opt/nccl-ring/…` (y el `LD_PRELOAD` apuntaba al mismo sitio vacío). El pull del volumen sí funcionó.

- Montaje con `subPath: opt/nccl-ring` (los volúmenes `image` lo admiten desde k8s 1.33; el clúster es v1.36.2+k3s1): las rutas de `nccl_sonda.py` quedan como estaban.
- Un Job no se puede cambiar: `sparks-nccl-sonda-v3b-dgx1/2/3` (label `app: sparks-nccl-sonda-v3b`) y los `sparks-nccl-sonda-v3-dgxN` salen del render, para que el prune de `ai` se los lleve. Los v1 y v2 no cambian.
- Test nuevo que falla con el montaje de #156: lleva las tres rutas del Dockerfile de main, a través del montaje de cada Job, y exige que casen con `LIB_PARCHEADA` y `GENERADOR` de la sonda (y `ring.conf` junto al generador). Comprobado en rojo quitando el `subPath`.

Evidencia: `.company/evidence/DGX-815-sonda-v3-subpath.md` (60 tests OK con y sin `NCCL_RING_DIR`, ruff 0.12.4, `--dry-run=server` de los tres Jobs v3b). No se ha tocado el clúster.

## Alcance de esta PR
- C1: sonda NCCL v3b por Spark (montaje del volumen image corregido)
- C2: test de rutas del montaje y de los Jobs v3b

🤖 Generated with [Claude Code](https://claude.com/claude-code)

