Rol: it · Fecha: 2026-10-09T23:55:00Z · Sesión: f6ba0b0b-5ceb-421e-9db5-dbaee767a1fc · Estado: LISTO

# SC-2185 · Conector social: escrituras fallan con READONLY tras failover de valkey

## Problema
Tras el failover de shared-valkey del 08-10 16:39Z, el pod `mcp-sse` quedó con sus conexiones TCP contra la IP del ex-master (ahora replica read-only): toda escritura `social_send_message` fallaba con `READONLY You can't write against a read only replica`; las lecturas OK. Mitigado el mismo día borrando el pod; este Request trae el arreglo permanente (PR #244, k8s-socialmedia-pocharlies, rama deploy/prod).

## Criterios de aceptación
- [ ] Tras el merge y el sync de la app ArgoCD `socialmedia`, el pod `mcp-sse` tiene `REDIS_SENTINELS=shared-valkey-sentinel.databases.svc.cluster.local:26379` y `REDIS_MASTER_NAME=shared-cache-master`.
- [ ] 0 errores READONLY en los logs del namespace `whatsapp-mcp` tras el despliegue.
- [ ] `social_send_message` escribe en telegram `personal` y `professional` sin borrar ningún pod.
- [ ] El aviso del caso ACC-21 (texto en su descripción) queda publicado en el topic «Secretaría» desde una cuenta de Dani (no desde el bot).
