SC-2277 fix(claude-rc-status): el primer volcado de la caché no depende del uptime del host

## Qué
`_agg_ultimo_volcado` arrancaba en `0.0` como «nunca volcado», pero el debounce compara contra `time.monotonic()`, que cuenta desde el arranque del host. Con menos de `AGG_FLUSH_MIN_S` de uptime el primer volcado de la caché del índice no escribía; en CI hizo fallar `test_volcado_del_indice_debounced` en un runner recién reiniciado.

El centinela pasa a `float("-inf")` (código y tests): el primer volcado escribe siempre. Un test nuevo fija el reloj monotónico a 5 s con `AGG_FLUSH_MIN_S = 3600` sobre un módulo recién cargado, y falla sin el arreglo.

El reloj falso se aplica con `unittest.mock.patch.object(m, "time", ...)` como context manager: sustituye solo la referencia `time` del módulo cargado en el test, se restaura al salir y no toca el `time.monotonic` real del proceso.

## Alcance de esta PR
- C1: el estado inicial de «nunca volcado» no depende del uptime del host (código y test)
- C2: test que fija monotonic() pequeño y comprueba que el primer volcado escribe

## Verificación
`python3 -m unittest ci/test_claude_rc_status.py` → 137 tests OK (incluye el nuevo); con el centinela original `0.0`, el test nuevo falla (`AssertionError: False is not true`). `company-duplicados`: sin duplicación nueva.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

