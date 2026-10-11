# DGX-820 · criterios del 00-spec.md

- [ ] C1. PR de gitops que lleva la app `ai` a la ventana de los Sparks (92fb200, overlays/sparks-ventana-20261010). El render no tiene ningún Deployment de qwen38 y la pausa deja el árbitro en sync-paused con la voz a 0. El comentario lleva el rollback a qwen38 TP=3 (01f9b4d, overlays/qwen38-tp3-ventana-20261010).
- [ ] C2. Si hace falta, un overlay `glm53-tp3-ventana-k64-20261010` en la línea pin/glm53-ventana-20261010. Es el modo k64 del overlay k64 de main (dispram y pagesize 65536) con la receta NCCL, MENTAT_FABRIC_IP y KV que funcionaron en k4, y tiene tests.
- [ ] C3. Al terminar, PR de gitops que devuelve `ai` a qwen38 TP=3 en 4K.
