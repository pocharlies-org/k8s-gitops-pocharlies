# DGX-816 · criterios del 00-spec.md

- [ ] C1. prepare_padded.sh pasa un `--from-file` por cada scripts/glm53/manifest-*.json existente, construidos en un array fuera de la palabra `--from-file=`.
- [ ] C2. Un test de scripts/glm53/test_host_scripts.py falla con la línea vieja y pasa con la nueva.
- [ ] C3. No cambia nada más del script: la imagen por digest, el Job y el modo --esperar quedan igual.
