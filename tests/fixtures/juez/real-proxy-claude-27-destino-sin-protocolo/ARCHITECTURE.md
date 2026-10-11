# ARCHITECTURE — proxy-claude

**Fuente de verdad del router de modelos de Claude Code.** Un proxy local por modelo en `127.0.0.1:18791`: el nombre del modelo decide a dónde va cada petición. `claude-local-router` lleva una copia suya y `claude-router` es la versión antigua.

## Clientes y versiones

- Claude Code en terminal y en el panel de VS Code (sin envoltorio: el selector persiste el modelo y el router enruta) y la statusline `bin/claude-statusline` (🟢 LOCAL / 🔵 ANTHROPIC / 🔴 ROUTER CAÍDO).
- Las sesiones de la compañía (Remote Control siempre locales, por la cabecera `x-claude-router-force-local`).
- Plataformas: Linux (`systemd/claude-router.service`, `Restart=always`) y macOS (`launchd/com.pocharlies.claude-router.plist`).
- Versionado: el router no lleva versión en su código ni en el README; los hitos van por commit y PR (el último, `0bdff15` #20, 26-09-2026, eventos de cambio de backend por sesión). La versión 2.7.0 la declara el plugin `claude-local-router`, no este repo.

## Dependencias (en ambos sentidos)

- Depende de: LiteLLM (ns `litellm`; el catálogo vive en `k8s-litellm-pocharlies`), `api.anthropic.com` y el panel DGX para la configuración de enrutado (`CLAUDE_ROUTER_ROUTING_CONFIG_URL`, interruptor «Claude» de la compañía y `claude_gate`).
- Dependen de él: todas las sesiones de Claude Code del x86 y del Mac; `claude-local-router` (copia empaquetada); la unidad `claude-router-front.service` del host en `x86-host-runtime-pocharlies` (vínculo exacto no verificado).
- Contrato implícito con el panel: la forma de la configuración de enrutado; cambiarla exige tocar `dgx-infra` en el mismo cambio.

## Stack

Node sin dependencias (`bin/claude-router.js`, 626 líneas), shell (`install.sh`), unidades systemd y launchd, y smokes en Node (`tests/smoke-*.js`).

## Componentes compartidos

- `bin/claude-router.js`: **el** router. Ruteo por modelo; `GET /v1/models` local (sin esto el CLI valida `--model` contra el catálogo de Anthropic y falla con `unrecognized_model`); sustitución de credenciales (el OAuth de Anthropic nunca sale hacia LiteLLM); guardarraíl de historial mezclado (`CLAUDE_ROUTER_MIXED=strip`); `claude_gate` (la compañía solo saca a Anthropic los modelos de su lista); contador de peticiones de la compañía en vuelo; 403 en vez de salir a Anthropic cuando el interruptor «Claude» está apagado; línea de log `LIMITE-429` (SC-2161 P1) por cada 429 que devuelve Anthropic, con `src` (hash corto del token, nunca el token), modelo, `error.type`, `retry-after` y las cabeceras `anthropic-ratelimit-*`: solo observa, el 429 sigue al cliente intacto.
- `bin/claude-statusline`: indicador de backend.

## Cómo se construye

Un cambio de ruteo se hace solo aquí y, en el mismo ciclo, se actualiza la copia de `claude-local-router/plugins/local-router/bin/claude-router.js` (el job `bundle-drift` lo vigila). Sin dependencias de npm. Una variable de entorno nueva se documenta en `env.example`.

## Tests

`tests/smoke-backend-flip.js`, `smoke-company-claude-gate.js`, `smoke-company-inflight.js`, `smoke-limit-log.js` y `smoke-plan-gate.js` (smokes de Node; no se verificó que CI los ejecute).

## CI/CD y despliegue

`.github/workflows/bundle-drift.yml` (runner `ubuntu-latest`; se dispara con cambios de `bin/claude-router.js`, la unidad o el propio workflow): falla si la copia del plugin público `claude-local-router` diverge. Además los workflows estándar `duplicados.yml` y `pr-review.yml`. Despliegue: `./install.sh --statusline` copia el router a `~/.local/bin` y activa la unidad; solo los procesos nuevos leen la URL.

## Decisiones y trampas

- El 21-09-2026 la copia congelada del plugin se llevó por delante perfiles de chat de OWU-50 y reactivó el desvío a Opus retirado el 17-09; `bundle-drift` es lo que lo impide. El repo del plugin es público y este privado: la comprobación va aquí.
- Los dos desvíos automáticos (local saturado → nube, cuota → local) se retiraron el 17-09-2026 con su código; ningún `CLAUDE_ROUTER_FALLBACK_*` se lee ya. La saturación local la gestiona la admisión de LiteLLM.
- `behavesAs: sonnet` en las filas locales del selector: sin eso el CLI aborta con «Prompt is too long» ante un modelo desconocido.
- El job de CI en `ubuntu-latest` debería ir a `arc-k8s`.
