SKIRM-111 feat(host): notify-synapse-monitor firma sus envíos al conector de Telegram

## Alcance de esta PR

- C3: `notify-synapse-monitor.sh` firma leyendo el secreto de un fichero 0600; no hay secreto en el repo, en `argv` ni en el log; prueba con un secreto de prueba y `shellcheck`; el script comprueba permisos y propietario del fichero sin imprimir el valor.

## Comportamiento con la clave (a propósito)

- **Fichero de clave inválido (modo, propietario o vacío) → exit 1 con el motivo en stderr y sin envío, a propósito.** Es un error de provisión y no debe enviar nada sin firma en silencio. El motivo concreto sale por stderr antes del aviso general y la clave nunca se imprime; una prueba por motivo lo fija.
- **Sin fichero → aviso y envío sin firma mientras el conector no exija firma.** Es la transición que pidió la spec (el conector aún no exige): cuando exija, ese envío recibe 401 y el script sale con 1 imprimiendo la respuesta del conector.
- La asimetría es deliberada: «no existe» es la transición; «existe pero no vale» es un error.

## Qué cambia

- El script firma con HMAC los bytes exactos que envía a `POST /api/public/send/:chatId` del conector de Telegram, como `createHMACAuth` (`sha256=HMAC(clave, "<ts>:<cuerpo>")` en `x-connector-signature`, `x-connector-timestamp` en segundos). El conector verifica sobre `JSON.stringify` del cuerpo que parseó, así que el cuerpo enviado tiene que ser el que escribiría `JSON.stringify`.
- `jq` no lo es: escribe DEL como `\u007f` y `JSON.stringify` lo deja en crudo, y la firma no casaría, sin avisar, con un mensaje que llevara ese carácter. El cuerpo y la firma salen ahora de un único `python3` (`json.dumps(ensure_ascii=False, separators=(",", ":"))`, la misma receta que `telegram-sync` y el panel) y `curl` envía esa misma cadena con `--data-binary`: nada se serializa dos veces. Se retira `jq` del script.
- La clave sale de un fichero 0600 (`CONNECTOR_SECRET_FILE`, por defecto `/home/dibanez/.config/notify-synapse-monitor/connector-secret`; no va bajo `$HOME` porque el timer lo ejecuta como root y los DGX entran por ssh como `dibanez`). El script lo rechaza si no es un fichero normal, de modo 600 y del propietario esperado (`CONNECTOR_SECRET_OWNER`, por defecto `dibanez`), o si está vacío. La clave solo la lee el proceso de `python3`: nunca pasa por `argv` ni por el log. La cabecera del script documenta cómo provisionarlo desde 1Password sin imprimirlo (el Secret que construye el ExternalSecret del item `whatsapp-mcp`, campo `CONNECTOR_SHARED_SECRET`) y cómo comprobarlo con `stat` y `sha256sum | cut -c1-12`.
- Sin fichero de clave, el script avisa y envía sin firma (solo vale mientras el conector no exija firma).
- El destino pasa de una ClusterIP fija al nombre DNS del Service (`telegram-connector.whatsapp-mcp.svc.cluster.local:3002`), que no se rompe si el Service se recrea. `CONNECTOR_URL` sigue permitiendo cambiarlo.
- `--help` imprime la cabecera hasta la primera línea en blanco, no un rango fijo de líneas.
- La interfaz del script (argumentos, salida, códigos de salida) no cambia. Variables nuevas: `CONNECTOR_SECRET_FILE`, `CONNECTOR_SECRET_OWNER`.

## Verificación

Detalle en `.company/evidence/SKIRM-111-notify-synapse-monitor-hmac.md`.

- `tests/test_notify_synapse_monitor_signing.py`, añadido al job `manifests`: 23 de 23, ninguna omitida. Usa los vectores literales de `connectors/telegram/src/api/public-routes.test.ts` (k8s-socialmedia-pocharlies), coteja el cuerpo con `JSON.stringify` de `node` para U+0001 a U+2FFF más emoji, y ejecuta el script entero contra un conector local que verifica como la puerta del conector (DEL, emoji, comillas y un `\u007f` escrito a mano; la clave no sale por la salida ni por los argumentos de `curl`).
- La prueba muerde: con el cuerpo escapando DEL como `jq` fallan 3 pruebas; con el stderr de `sign_request` redirigido a `/dev/null` fallan las 3 que fijan el motivo concreto de un fichero de clave rechazado (modo, propietario, vacío).
- Nada se omite en CI: el job `manifests` prepara `node` 22 (`actions/setup-node@v4`, el mismo paso que `dashboard-tests` ya usa en `arc-k8s`) y, con `CI` definido, una herramienta que falte (`node`, `curl`, passwd del uid) hace fallar la prueba en vez de omitirla; fuera de CI se omite. Comprobado en el x86 con un PATH sin `node`: `CI=1` falla, sin `CI` omite. Un job verde implica que corrió.
- `bash -n` y `shellcheck` 0.11.0 sin hallazgos.

## Documentación

`ARCHITECTURE.md`, sección «Instalaciones del host (no GitOps)»: entrada del script (dónde corre, el fichero de clave en modo 600 y propietario `dibanez`, y la comprobación de `release` de que el fichero del host coincide por `sha256sum` con el del commit fusionado). La cabecera del script documenta cómo provisionar y comprobar el fichero de clave.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

