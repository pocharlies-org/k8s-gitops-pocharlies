# DGX-815 · criterios del 00-spec.md

- [ ] C1. El repo trae un `.patch` contra NCCL v2.30.7-1 (fijado por commit) que solo cambia el cálculo de `index` en
- [ ] C2. `images/nccl-ring/Dockerfile` compila `libnccl.so.2` solo para sm_121 y arm64, sobre un CUDA compatible con la
- [ ] C3. Un workflow de CI construye la imagen para linux/arm64 y la sube a Harbor por digest, con el mismo patrón que
- [ ] C4. `k8s/nccl-ring/nccl_ring_graph.py` (solo librería estándar) lee la copia congelada de ring.conf y, con el host y
- [ ] C5. Los tests del generador reproducen la tabla que validó qa en DGX-810: dgx2 recibe 1,3 y envía 0,2; dgx1 recibe
- [ ] C6. No toca la línea de la ventana (`pin/sparks-ventana-20261010`), ni el residente, ni ningún manifiesto desplegado:
