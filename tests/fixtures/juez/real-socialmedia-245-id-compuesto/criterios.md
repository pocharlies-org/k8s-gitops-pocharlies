Rol: tech-lead · Fecha: 2026-10-08 · Sesión: 715ef7e4-8c79-4f49-a12d-59a7c4339ea7 · Estado: LISTO

# SKIRM-106 · F4c Conector WhatsApp: novedades (canales y estados), solo lo que falte

Repo: k8s-socialmedia-pocharlies · Tronco: `deploy/prod` · Reglas comunes: SKIRM-99 §4. Rol: developer, 1 maker. En serie: después de F4b. CONDICIONAL.

## Qué y por qué
Estados y canales ya están: `connectors/whatsapp-web/src/statuses.ts` se documenta a sí mismo como "la mitad de almacenar, leer y publicar de las novedades del fork, adaptada a prod"; tabla `whatsapp_statuses` (migración 019); los mensajes de `status@broadcast` y de `<id>@newsletter` caen en `messages`; tools `social_list_statuses`, `social_publish_status`, `social_list_channels`, `social_list_channel_posts`, `social_lookup_channel`, `social_manage_channel_subscription`. Lo que el fork añade (`novedades-store.ts`, `novedades-channels.ts`, `novedades-ingest.ts`, `novedades-reader.ts`) y puede que prod no tenga:
1. Directorio persistido de canales seguidos (`whatsapp_novedades_channels`).
2. Identidad de un post de canal por canal: los ids de newsletter solo son únicos dentro de su canal (validado por el fork sobre Baileys rc13). En prod se guardan en `messages` con id global por cuenta: **posible colisión entre canales**, sin verificar.
3. Tumbas de estados y posts borrados (borrado blando).

## Paso 0 (solo lectura; puede correr durante la ola A)
Copiar sin código `novedades-store.test.ts`, `novedades-channels.test.ts`, `novedades-ingest.test.ts`, `novedades-reader.test.ts`, `novedades-controller.test.ts`, `novedades-status-send.test.ts`, `controller-novedades-status.test.ts`, `statuses.test.ts` (versión del fork) y `statuses.postgres.mjs`. Se ejecutan de uno en uno con `pnpm --filter ./connectors/whatsapp-web exec tsx --test <fichero>` (el script `test` es una lista explícita y el filtro se ignora).

Clasificación obligatoria de cada test en `50-entrega.md`: **(a)** aserción que falla sobre un módulo que prod YA tiene (`statuses.ts`): candidato; **(b)** falla porque el módulo (`novedades-*.ts`), el DDL o la ruta del fork no existen en prod: **casi todos los de esta historia serán (b)** y no prueban ningún hueco; **(c)** depende de una ruta excluida (`/novedades/*`): se rechaza. Lo que pasa ya lo tenemos.

Como casi todo será (b), la evidencia viene de **pruebas de comportamiento de prod escritas por el maker** y en rojo contra el tronco: (1) ingerir dos posts con el mismo id de newsletter en dos canales distintos con el código de prod; (2) un borrado que llega antes del post, para ver si lo resucita. **Si ninguna falla de forma que importe, la historia se cierra sin PR con el cuadro** (ya está en producción).

## Origen candidato (head `7b81bd24`)
Solo lo que el paso 0 justifique de `novedades-store.ts`, `novedades-channels.ts`, `novedades-ingest.ts`, `statuses.ts`. El DDL del fork (`connectors/whatsapp-web/migrations/002_novedades_persistence.sql` y `ensureNovedadesTables`) **no se copia**: se reescribe como migración nueva en `mcp-server`.

## Excluido
Las 13 rutas `/novedades/...` (son de la UI del fork), `novedades-communities.ts` y `/communities/:jid/action` (prod ya tiene `social_manage_community`), `ensureNovedadesTables`, cualquier `CREATE TABLE` en tiempo de ejecución, `connectors/whatsapp-web/migrations/*`, `NOVEDADES-STORE.md` (se resume en `ARCHITECTURE.md` si se adopta algo).

## Criterios de aceptación
- [ ] C1. Cuadro del paso 0 en `50-entrega.md` con cada test clasificado (a), (b), (c) o "pasa" y el resultado de las dos pruebas propias; si no hay hueco, cierre sin PR (resultado, no fallo). Todo test nuevo va a la lista explícita de `scripts.test` de `connectors/whatsapp-web/package.json`, con `fetch` y sin `supertest`.
- [ ] C2. Si hay colisión demostrada: dos posts de canales distintos con el mismo id coexisten y cada uno se lee de su canal (`social_list_channel_posts` por canal). Test que falla en prod y pasa tras la PR.
- [ ] C3. Si se persiste el directorio de canales: migración `021_whatsapp_novedades_channels.sql`, aditiva, `IF NOT EXISTS`, PK `(account, channel_jid)`, sin tocar ni leer tablas existentes; el conector degrada con aviso cuando la tabla no existe (patrón de `statuses.ts`, `42P01`), de modo que el orden conector/migración no importa. Prueba con el sandbox de SKIRM-89.
- [ ] C4. Aislamiento de cuentas: la misma tabla no mezcla filas de personal, professional y leila. Test con tres cuentas.
- [ ] C5. Un borrado antes de la llegada del post no lo resucita (tumba). Test.
- [ ] C6. Los estados siguen leyéndose de `whatsapp_statuses`/`messages` como hoy: test de caracterización previo que pasa antes y después.
- [ ] C7. Ninguna tool cambia; `pnpm -r test` verde; `ARCHITECTURE.md` (§4 tablas, §8) actualizada; `Co-authored-by:`.

## Test que debe fallar antes
El de C2 (colisión de ids) y, si procede, el de C5; ambos escritos y mostrados en rojo contra prod antes de implementar.

## Migraciones
Como mucho `021_whatsapp_novedades_channels.sql`: **solo tabla nueva, sin índices ni DDL sobre `messages`** (`migrate.ts` envuelve cada fichero en `BEGIN`/`COMMIT`; `CREATE INDEX CONCURRENTLY` no cabe en una migración y el precedente de prod es construirlo en runtime, `search.service.ts:533`). Si el paso 0 lo pide, el maker se detiene y llega al architect. Probada contra el esquema de prod con el sandbox de SKIRM-89, que debe estar fusionado. Sin tocar `_migrations` ni el runner. El patrón `42P01` de `statuses.ts` (tolerar tabla ausente) es el correcto.

## Referencias (obligatorio en el brief)
Referencias: `connectors/whatsapp-web/src/statuses.ts` (patrón `42P01`), migración 019, `mcp-server/src/infrastructure/database/migrate.ts`. No construir: rutas `/novedades/*`, `novedades-communities.ts`, `ensureNovedadesTables`, DDL en runtime, índices en migración.
Framework: Node 22 + TypeScript, `tsx --test` con lista explícita en `package.json`; migraciones SQL de `mcp-server` aplicadas por el Job PreSync.

## Cómo se verifica (qa)
Paso 0 y C2-C7 sobre la rama; migración aplicada sobre el sandbox y sobre una copia donde la tabla ya existe (idempotente); tras el release, `social_list_channels` y `social_list_channel_posts` de la cuenta de prueba.

## Riesgos
Reinicia los conectores de WhatsApp (misma imagen y mismo pin que F4a/F4b; conector a conector, el personal el último, `restartCount` estable 24 h). La migración corre en el Job PreSync: una tabla nueva no bloquea nada; ningún índice ni DDL sobre `messages`.
