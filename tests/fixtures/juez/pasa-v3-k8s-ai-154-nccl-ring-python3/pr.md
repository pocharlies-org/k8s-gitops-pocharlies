DGX-815: el build de nccl-ring instala python3 (run 38062797791 falló en nccl_git_version.h) y un test lee los intérpretes del fuente de NCCL

## Qué cambia

El primer build real de `images/nccl-ring/Dockerfile` (run 38062797791 de `build-nccl-ring-image.yml`, en el builder de dgx3) cayó en `make src.build`, al generar `nccl_git_version.h` (`src/Makefile:99`): `/usr/bin/env: 'python3': No such file or directory`. La base `nvidia/cuda:13.0.2-devel-ubuntu24.04` no trae python3.

- `images/nccl-ring/Dockerfile`: `python3` en el `apt-get` de la etapa de build.
- La clase, no solo el caso. Revisado en NCCL v2.30.7-1 (`73cf1122`) lo que ejecuta `src.build`:
  - Scripts: `src/misc/generate_git_version.py`, `src/device/generate.py` y `src/device/symmetric/generate.py` (los tres `#!/usr/bin/env python3`). Los tres importan solo la librería estándar (`os`, `sys`, `shutil`, `re`, `platform`, `subprocess`, `pathlib`): no hace falta ningún módulo de pip ni `python3-venv`.
  - Resto de herramientas de los Makefile: `bash` (`SHELL := /usr/bin/env bash` en `src/device/Makefile`), `sed`, `cut`, `grep`, `realpath`, `fmt`, `install`, `ln` (coreutils/base), `which` (debianutils), `ar`/`g++`/`make` (build-essential), `git` (ya instalado), `nvcc` y `cuobjdump` (la base devel: `cuda-minimal-build-13-0` → `cuda-compiler-13-0` → `cuda-cuobjdump-13-0`, según el índice de paquetes de NVIDIA). Nada más que instalar.
- `tools/test_nccl_ring.py`:
  - `test_el_apt_get_de_la_etapa_de_build_instala_python3` (siempre, también en `ci.yml`).
  - `test_los_interpretes_que_ejecuta_el_build_de_nccl_estan_en_el_apt_get` (con `NCCL_SRC`, como el test del parche): lee de los `Makefile` de `src.build` los `./<ruta>.py` que ejecutan, saca el intérprete de cada shebang y exige que su paquete esté en el `apt-get` (un intérprete sin paquete conocido falla), y que sus imports sean de la librería estándar.
  - `nccl_src()`: el checkout de `NCCL_SRC` con su comprobación de commit, que ya hacía el test del parche, ahora compartida.

## Alcance de esta PR

- C2: `images/nccl-ring/Dockerfile` compila `libnccl.so.2` (el build ya no cae por falta de `python3`; el resto del Dockerfile no cambia: sm_121, arm64, imagen final con la lib, el generador y ring.conf).

No toca el cluster, no lanza el workflow, no toca la línea de la ventana ni el residente.

## Verificación

```
$ python3 -m unittest tools/test_nccl_ring.py
Ran 19 tests in 0.130s
OK (skipped=2)

$ NCCL_SRC=<checkout 73cf1122> python3 -m unittest -v tools/test_nccl_ring.py
test_el_apt_get_de_la_etapa_de_build_instala_python3 ... ok
test_los_interpretes_que_ejecuta_el_build_de_nccl_estan_en_el_apt_get ... ok
test_aplica_limpio_sobre_nccl_v2_30_7_1 ... ok
Ran 19 tests in 0.154s
OK
```

Sin `python3` en el `apt-get` fallan los dos tests nuevos (`not less than or equal to {'git', 'ca-certificates', 'build-essential'}` y, por cada script, `'python3' not found in {...}`). `ruff check` (el bloqueado de `requirements-ruff.txt`) y `company-duplicados`: limpios.

Lo que esta PR no prueba: que el build completo llegue al final. Solo lo dice el siguiente run de `build-nccl-ring-image.yml`, que lanza la sesión.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

