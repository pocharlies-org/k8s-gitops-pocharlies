SKIRM-106 fix(whatsapp-web): un post de canal con el id de otro canal ya no se pierde (F4c)

## Alcance de esta PR

- C1: cuadro del paso 0 con cada test del fork clasificado (a), (b), (c) o «pasa» y las tres pruebas de comportamiento propias (`.company/evidence/SKIRM-106-f4c.md`); los tests nuevos van a `statuses.test.ts`, que ya está en la lista explícita de `scripts.test`
- C2: dos posts de canales distintos con el mismo id coexisten y cada uno se lee de su canal; pruebas 10, 12 y 14 de `statuses.test.ts`, rojas sobre el tronco (`expected 'professional:222@newsletter:SAME', actual 'professional:SAME'`) y verdes tras el cambio
- C6: las pruebas de estados de `statuses.test.ts` (ingest, lectura por autor, índice ausente `42P01`, posts de canal) pasan antes y después sin tocarlas, más dos de caracterización del id desnudo sin choque
- C7: ninguna tool cambia; suite de whatsapp-web verde (582 tests, 581 pasan, 1 omitido); `ARCHITECTURE.md` §8 actualizada (§4 no cambia: esta PR no añade tabla); `CONTRACTS.yaml`: solo la nota de `http.whatsapp-connector.channels-posts.v1` («Ids bare, except a post whose id another channel already holds: its messageId is `<channelId>:<id>`»; sin `.v2`, `Contract-Change: migrate`)

## Qué cambia

El id de un mensaje de un canal solo es único dentro del canal, y `messages.wa_message_id` es una clave por cuenta con `ON CONFLICT DO NOTHING`: el post de un segundo canal con un id ya ocupado se descartaba sin rastro y su `whatsapp_message_keys` pisaba la del primero.

`channelPostMessageId` (`connectors/whatsapp-web/src/statuses.ts`) deja el id tal cual salvo que otro canal ya lo tenga; entonces el post se guarda, con su clave, bajo `<jid del canal>:<id>`. El ingest (`ingestMessage`) y el revoke o la edición que nombran el post (`handleInboundMutation`) usan la misma función, así que llegan a la fila de su canal. El prefijo de cuenta lo pone `accountKey` al escribir (`storeMessage`) y al mutar (`markMessageRevoked`, `markMessageEdited`): la prueba 10 espera `professional:222@newsletter:SAME`. Sin migración y sin tocar filas existentes; si la consulta falla se usa el id desnudo, como hasta ahora.

Residual: `whatsapp_message_payloads` guarda una copia por id; con un id repetido gana el último post.

## Fuera de esta PR

C3, C4 y C5 (directorio persistido de canales seguidos, aislamiento de cuentas de esa tabla y tumba de un borrado que llega antes del post): las pruebas propias P2 y P3 del cuadro fallan, y su arreglo pide una tabla nueva (migración `021_…`, aditiva) que depende del sandbox de SKIRM-89 fusionado. No se escribe aquí.

## Autoría adoptada

Ningún commit copia código del fork. Se adopta el principio de `NOVEDADES-STORE.md` de la PR #74: los ids de un canal solo son únicos dentro de ese canal.

Co-authored-by: Jordi Ibáñez <staticduo@gmail.com>

🤖 Generated with [Claude Code](https://claude.com/claude-code)

