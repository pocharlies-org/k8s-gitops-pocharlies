INFRA-776: GET /api/sessions devuelve chat_id y thread_id por fila

## Cambio

- `GET /api/sessions` (`gateway/platforms/api_server.py`) añade a cada fila `chat_id` y `thread_id`: el topic de Telegram al que la sesión está ligada (lectura inversa de `telegram_dm_topic_bindings` por `session_id`).
- Null cuando la sesión no tiene topic o no es de Telegram.
- Aditivo: ningún campo existente cambia de nombre ni de forma. Auth, allowlist y config de Hermes no se tocan.
- La lectura por fila va en `asyncio.to_thread`, igual que el resto de lecturas de la base.

## Tests

- `tests/gateway/test_session_api.py::test_list_sessions_carries_telegram_topic_fields`: fila ligada a topic (chat_id y thread_id), fila de Telegram sin topic (null), fila de otra fuente (null), y las claves previas siguen. Pasa en local.
- El CI de la PR no ejecuta los tests Python: el workflow `CI` (`ci.yaml`, el que llama a `tests.yml`) está `disabled_manually` en el repo, y `Docker Build, Test, and Publish` (`docker.yml`) no corre pytest. La evidencia de tests es la corrida local, no CI.

## Base de la PR

- La rama parte de `overlay/dgx-586-578` (2768af3b7b). Su `api_server.py` es byte a byte el de la imagen viva `fork-f24a9c7-p3426968` (sha256 comprobado en la imagen).
- El diff de la PR contra esa base es solo este cambio de `api_server.py` más la línea de decisión en `ARCHITECTURE.md` §8.

## Despliegue

- Esta rama no es `overlay/**`: el push a esta rama no lanza `hermes-overlay.yml`.
- Al hacer merge en `overlay/dgx-586-578` sí se lanza. Construye `docker/Dockerfile.overlay` con `ARG BASE` = `fork-f24a9c7-p3426968` (el tag que corre el pod) y un único `COPY` de `api_server.py`, y sube el tag nuevo `fork-f24a9c7-p05fbbc7` de `docker/overlay-tag`. No toca `fork-f24a9c7-pbddbbb7`.
- La imagen viva no cambia con esta PR. El pin en `values.yaml` de `k8s-openclaw-qwen36-pocharlies` (`deploy/prod`) y el reinicio con `hermes-despliegue.yml` los lleva release tras el merge.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

