DGX-820: overlay glm53-tp3-ventana-k64-20261010 (GLM TP=3 de la ventana en modo k64)

## Alcance de esta PR

- C2: overlay glm53-tp3-ventana-k64-20261010

## Qué cambia

Añade `overlays/glm53-tp3-ventana-k64-20261010`, el modo k64 de GLM-5.3-Flash TP=3 para medirlo con los Sparks en el kernel de 64K. Su base es el overlay k4 de la ventana (`overlays/glm53-tp3-ventana-k4-20261010`, DGX-818), sin copiar nada de él: la receta NCCL con la libnccl parcheada y el grafo `--order dgx3,dgx1,dgx2`, MENTAT_FABRIC_IP en la LAN, el ARX de la receta y la pausa de la ventana son los del k4. Cambia solo lo que cambia el modo k64 de main (`overlays/glm-5.3-flash-tp3-k64-20261010`):

- El ConfigMap de modo: EXPECT_PAGESIZE=65536, REQUIRE_DISPRAM=1, DRIVER_VERSION=610.57.04 y PYTHONPATH=/opt/dispram.
- `patch-dispram.yaml`, el de main sin tocar: `/run/dispram` en solo lectura y el socket aparte en rw (S-1), el plugin en `/opt/dispram` en ro. Solo lo montan los tres rangos de GLM (S-2).

## KV_CACHE_MEMORY: 12 GiB

El k64 de main lleva 18 GiB: los 16 del k4 de main más 2 GiB que presta dispram. Los 16 son los que dejaron a dgx3 sin memoria disponible en la compilación JIT de CUDA de la ventana (DGX-818), y el k4 de la ventana midió bien con 12. Main no justifica ninguna cifra mayor para estos nodos, porque los 2 GiB de dispram no están medidos aquí. Se queda en 12 GiB, y así el k64 se mide contra el k4 con el mismo KV y cambia solo el kernel. Subirla es cambiar un literal del overlay.

## Verificación

Evidencia completa en `.company/evidence/DGX-820-glm-k64.md`. No se ha tocado el cluster: solo `kubectl kustomize`.

- Tests en rojo primero (f661b29 y f26a586): `ModoK64Test` falla porque el overlay no existe.
- `python3 -m unittest tools/test_glm53_tp3_ventana.py`: 39 tests, OK (27 de DGX-818 y 12 del k64). Con `tools/test_sparks_ventana_pin.py`: 104 tests, OK, 1 omitido (el de NCCL_RING_DIR de la sonda, el de siempre).
- El render del k64 es el del k4 salvo el ConfigMap de modo (otro hash), sus referencias y los volúmenes y montajes de dispram.
- Los renders del k4 y de la ventana son los de 66a7553 (`K64NoCambianTest`).
- Los tests viven en el fichero de los de la ventana, que CI ya corre: `ci.yml` y `check_ci_security.py` no se tocan. `ruff` 0.12.4 sin avisos.

Que containerd monte el socket suelto con el directorio en ro, `check-host` con `dispramd` vivo y las medidas de 64K contra las de 4K son de la ventana, no de este diff.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

