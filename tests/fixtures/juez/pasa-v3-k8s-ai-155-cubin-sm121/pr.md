DGX-815: la comprobación de cubin de nccl-ring acepta sm_121 y los sm_100 que NCCL fuerza (run 38063874568)

## Alcance de esta PR

- C2: `images/nccl-ring/Dockerfile` compila `libnccl.so.2` para sm_121 y arm64; la comprobación de cubin exige sm_121 y tolera exactamente los sm_100 que NCCL fuerza, cualquier otra arquitectura falla.

## Qué cambia

El segundo build de `images/nccl-ring` (run 38063874568) ya compila `libnccl.so.2` y cae en la comprobación posterior de `cuobjdump`, que exigía solo sm_121. El log de ese run lista 38 cubin: 28 `sm_121` y 10 `sm_100`. Los `sm_100` no los pedimos nosotros: NCCL v2.30.7-1 los compila aunque se pase `NVCC_GENCODE`, en `src/device/Makefile:48-50` (`NVCC_GENCODE_LDMC_FP8`, kernels LDMC FP8). En GB10 (sm_121) no se cargan.

- `images/nccl-ring/Dockerfile`: `sm_121` tiene que estar; `grep -qvE '^sm_(121|100)$'` hace fallar el build con cualquier otra arquitectura (`sm_100f`, `sm_90`, `sm_120`...). Comentario de una línea con la causa.
- `tools/test_nccl_ring.py`: test nuevo que extrae esa línea del Dockerfile y la ejecuta con `bash` sobre listas de cubin de ejemplo (pasan `{sm_121}` y `{sm_121, sm_100}`; fallan al añadir otra). Con el Dockerfile anterior el test falla.
- `.company/evidence/DGX-815-nccl-ring.md`: sección C2 con el run, los recuentos y la salida de los tests. `images/nccl-ring/README.md`: una línea.

No toca el cluster, la ventana, el residente ni ningún manifiesto, y no lanza el workflow: el build real lo vuelve a lanzar la sesión.

## Verificación

`python3 -m unittest tools/test_nccl_ring.py` -> Ran 20 tests, OK (skipped=2, los que piden `NCCL_SRC`). `docker buildx build --check --platform linux/arm64` sin avisos, ruff 0.12.4 y `check_ci_security.py` verdes, `company-duplicados` sin clones nuevos.

DGX-815

🤖 Generated with [Claude Code](https://claude.com/claude-code)

