SC-2185 fix(mcp-server): seguir el master de valkey por sentinel tras failover

## Que

Tras el failover de shared-valkey del 08-10 16:39Z, `mcp-sse` mantuvo sus conexiones TCP de larga vida contra la IP del ex-master (promocionado a replica) y **toda escritura social fallo con `READONLY You can't write against a read only replica`** (lecturas OK). Diagnostico completo en SC-2185.

## Cambio

- `createRedisClient()` (nuevo, `mcp-server/src/infrastructure/redis-client.ts`): con `REDIS_SENTINELS` (host:port por comas) + `REDIS_MASTER_NAME` define, construye el cliente ioredis en modo sentinel y **sigue al master promocionado**; las credenciales y el db se toman de `REDIS_URL`. Sin esas variables, comportamiento identico al actual (`new Redis(url, opts)`).
- Los 5 puntos de construccion de `new Redis(...)` del paquete pasan por el helper: `mcp/sse-server.ts`, `mcp/index.ts` y los servicios `llama` / `style-analysis` / `summarization` (misma clase del fallo).
- `k8s/base/manifest.yaml`: `REDIS_SENTINELS=shared-valkey-sentinel.databases.svc.cluster.local:26379` y `REDIS_MASTER_NAME=shared-cache-master` en `mcp-sse`, unico deployment del ns con conexiones reales a :6379 (medido en vivo: mcp-server y los conectores tienen 0 y su codigo no referencia Redis; por eso no llevan las vars).
- Test unitario del helper (4 casos: URL plana, modo sentinel con credenciales, varios sentinelas, variable incompleta). Suite completa: 701 pasan.

## Criterio de resuelto (SC-2185)

Tras el despliegue, 0 errores READONLY en los logs del ns y, en el proximo switch-master real del sentinel, `social_send_message` sigue escribiendo sin borrar pods.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
