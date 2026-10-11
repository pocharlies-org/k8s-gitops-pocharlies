# ARCHITECTURE.md — k8s-openclaw-qwen36-pocharlies

> Hoy el repo es sobre todo el chart **Hermes** (gateway de mensajería Telegram/WhatsApp con los perfiles `cto`,
> `analista`, `sre-devops`, `security`, `studio`…), más el legado OpenClaw (imagen, configs, docs). Una sola release:
> la instancia aparte `hermes-studio` se retiró el 02-10-2026 (el Studio es el perfil `studio`).
> Es el repo con el pipeline de despliegue **más delicado**: Hermes se despliega solo por `hermes-despliegue.yml`.
> Escrito por `architect` (SC-1426).

## 1. Clientes y versiones

| cliente | repositorio / ruta | versión desplegada | cómo se despliega |
|---|---|---|---|
| Hermes gateway (Telegram + WhatsApp, perfiles de la compañía) | `helm/hermes/` (`values.yaml`) | chart `0.1.0`, appVersion `v2026.9.14`; imagen `harbor.e-dani.com/homelab/hermes-agent:fork-f24a9c7-p3426968` (p73dfb4d + `tools/homeassistant_tool.py` de hermes-agent#10 + poda de rutas de perfiles retirados, hermes-agent#11 + pool de turnos y `x-litellm-session-id`, DGX-586/DGX-578 + `rate_limit` por ruta del webhook, hermes-agent#14, INFRA-697) | ArgoCD app **`hermes`** — sync **MANUAL** (sin `automated`); lo despliega `hermes-despliegue.yml` |
| Studio (perfil `studio` del gateway: las tools del Studio más las de los demás perfiles y `frenos: secretaria`, SC-1881) | `helm/hermes/values.yaml` → `profiles.studio`, `souls.studio`, ruta del grupo-foro «DGX Studio» (-1004396709845) | la del gateway | con el gateway (`hermes-despliegue.yml`) |
| Panel de Control Nexus (perfil `main`, «Hermes del panel», SC-2175: pestaña en todas las páginas del panel, solo lectura) | `helm/hermes/values.yaml` → `profiles.main` (solo `clarify` y `session_search`, sin Telegram, sin `servers`, sin fallback a Alibaba), `souls.main`, `apiServer.generatedKeys.main`; sin fila en `empresa.permisos`; cliente: `dgx-infra` `services/dashboard/` (`/api/hermes-panel/*` → `/p/main/`) | la del gateway | con el gateway (`hermes-despliegue.yml`); perfil, SOUL y key se recargan en caliente, sin reiniciar |
| OpenClaw legado (Dockerfile, `configs/openclaw`, docs) | raíz | pre-Hermes; README habla del namespace `openclaw-qwen36` | sin Application viva medida |

Clientes de Hermes: Telegram, WhatsApp y las apps (web/iOS) que usan su API `api_server`; el cambio de lo que ven los usuarios
debe tocar el chart y, cuando es la API, los clientes del repo del dashboard/iOS.

## 2. Dependencias, en ambos sentidos

- **Depende de** — AgentGateway (todas las tools MCP por rol, listadas en `values.yaml`), LiteLLM (modelos `tooling/high/max`),
  Harbor (`hermes-agent`, `harbor-pull`), 1Password/ExternalSecrets (`hermes-mcp-secrets`), nodos `node-pool=ks5-nvme`
  (nunca el `ubuntu` de casa), el repo `pocharlies-org/hermes-agent` (fork de la imagen), runners `arc-openclaw` y `x86-hermes`.
  Y para la identidad MCP por perfil de secretaria (INFRA-494, INFRA-479): Keycloak realm `edani`, un client
  confidencial `client_credentials` por perfil (`hermes-secretaria`, `-dani`, `-leila`, `-casa`, `-skirmshop`;
  roles acotados por ruta — las cuatro de casa/trabajo con `agentgateway-write:social/:workspace`, skirmshop solo
  `read`), cuyos `client_secret` viven en 1Password (items `hermes-kc-<perfil>`, campo `client_secret`) →
  ExternalSecret `hermes-kc-secretarias` (forma Connect del store `onepassword-connect`, `refreshPolicy: OnChange`,
  `templates/externalsecret-kc-secretarias.yaml`) montado como ficheros `/seed-secrets/kc/<perfil>/client_secret`
  **solo en el contenedor `agentgateway-auth-proxy`** (volumen `kc-secretarias`, `optional: true`; el contenedor
  `hermes` —el terminal de las secretarias— no ve ese volumen).
  El `sub` de cada perfil se liga a sus cuentas Google en `backends/workspace/identity-bindings.yaml` del repo
  `pocharlies-org/k8s-agentgateway-pocharlies` (tronco `main`) — un binding por perfil, mergeado ANTES de pasar
  el perfil a su puerto. Cada client `hermes-secretaria*` lleva un mapper de audiencia `oidc-audience-mapper`
  (`included.custom.audience: mcp.lan.e-dani.com`, igual que `agentgateway-mcp`): sin él el gateway responde
  401 InvalidAudience. Añadido a mano por devops en el realm edani (06-10-2026) — si Keycloak se reconstruye,
  hay que reañadirlo.
  Y para el perfil `jarvis` (INFRA-411): Home Assistant (`homeassistant.homeassistant.svc:8123`) con el token largo
  `hermes-jarvis` (1Password `hermes-homeassistant/HASS_TOKEN`, ExternalSecret propio `hermes-homeassistant` montado en
  `/seed-secrets/homeassistant`), y la integración Alexa Media Player
  de HA para hablar por el Echo (`notify.alexa_media_*`, `data.type: announce`).
  Y para la compuerta de pago (SC-1584, plugin `confirmar-pago`):
  - **Jira Cloud REST v3** (`e-dani.atlassian.net`) con la cuenta `secretaria`: token en 1Password item
    `jira-agent-secretaria/api_token` → ExternalSecret `hermes-pagos-secrets` (store `ClusterSecretStore/onepassword`,
    `templates/externalsecret-pagos.yaml`); el plugin no usa MCP de Jira, es REST directo con `urllib`.
  - **MCP `browser`** (agent-jake, nodo x86) por la ruta `/browser` de AgentGateway vía el auth-proxy del pod
    (`browserUrl`), con `connection: "x86"`: `browser_list_tabs`, `browser_switch_tab`, `browser_get_text`,
    `browser_click`, `browser_screenshot`, `browser_close_tab` (cierra la pestaña retenida al acabar, SC-1698);
    `browser_iframe_click` solo con `firma:"sca"`, para pulsar «Desconectar» de CaixaBankNow antes de cerrar. Ojo: `_pestanas()` (`plugins/confirmar-pago/__init__.py`) parsea el **TEXTO**
    de `browser_list_tabs` (`[id] título` + URL en la línea siguiente) — un cambio de ese formato en agent-jake deja
    todos los pagos en Bloqueada (fail-closed) y obliga a cambiar este lado.
  - **Backend del dashboard de control-nexus** (rutas de máquina `dgx.app.pagos.v1` en `dgx-infra`, repo
    `pocharlies-org/dgx-infra` branch master: `POST /api/pagos/{id}/decision`, `GET …/esperar`, `POST …/resultado`),
    en `dgx-dashboard-backend.control-nexus.svc.cluster.local:9002`, firmadas con HMAC V2. DOS secretos (veredicto del
    architect sobre dgx-infra#961): el general `control-nexus/dgx-dashboard-pagos` (→ Secret `hermes-pagos-hmac`) para
    `esperar`/`resultado`, y el propio `dgx-dashboard-pagos-decision` (→ `hermes-pagos-hmac-decision`) SOLO para
    `decision`, para que la secretaria —que tiene el general por pago-alerta— no se autoapruebe. Ambos llegan por
    ExternalSecret sobre el ClusterSecretStore kubernetes `kubernetes-control-nexus-pagos` (definido en
    `k8s-infra-pocharlies`: SA del ns `hermes` + Role/RoleBinding de solo `get` sobre esos dos Secrets) — sin 1Password.
    Antes de pedir nada el plugin lee el pago y lo ATA a esta compra (misma Acción, `tipo: compra`, importe y moneda,
    destinatario, estado `pendiente`): el `pago_id` lo escribe la secretaria en la nota y no puede autorizar un clic
    sobre otra decisión — veredicto del architect sobre #512. Canal APAGADO por defecto (`pagos.dashboardUrl: ""`):
    se activa con otra PR cuando dgx-infra#963 esté desplegado y el store de k8s-infra Valid. Sin URL ni secretos el
    plugin vuelve al flujo solo-Telegram de SC-1584 (optional:true + ES condicionado); sin atadura, Bloqueada.
  Y para la navegación de las secretarias (DGX-760, SC-2238): un segundo uso del MCP `browser`, aparte del del plugin de pago.
  - **Qué cargan**: `secretaria`, `secretaria-dani`, `secretaria-leila` y `secretaria-casa` cargan `browser` por la ancla
    `&sec-servers` de `values.yaml`, con solo las 27 tools del rol acotado `agentgateway-write:browser-navegacion` (catálogo en
    `k8s-infra-pocharlies` `platform/keycloak-next/ROLES.yaml`; regla CEL en `k8s-agentgateway-pocharlies#191`). Fuera: las 13
    sensibles y `run_code_unsafe`, que solo sirve el rol pelado. `secretaria-skirmshop` no carga `browser` (INFRA-492). Hasta que
    la #191 esté sincronizada, el registro del servidor `browser` da 403.
  - **El pin de `connection`**: los listeners por perfil (8791-8796, nunca el 8790 del plugin de pago, que ya fija `x86`) rechazan
    sin reenviar todo `tools/call` de `/browser` con `arguments.connection` presente y distinto de `x86` o su id; sin `connection`
    pasa. Falla cerrado ante un cuerpo que no es JSON, un lote con una llamada mala, más de 1 MiB y rutas con `/browser` en cualquier posición del path decodificado, sin frontera de segmento (`//browser`, `/browser;x`, `/browserX`, `/%62rowser`: solo sobrebloquea).
    La trampa: el pin es del proxy, no del gateway ni de Keycloak — el rol no distingue de qué Chrome es la conexión.
  - **Sin navegador nativo**: Telegram, `api_server`, cron y las rutas webhook `secretaria*` llevan la lista `&sec-toolsets`
    (lo de `hermes-telegram` menos `browser`, con el MCP como `mcp-browser`) y `toolSearch: "off"`. Un compuesto (`hermes-telegram`,
    `hermes-api-server`, `hermes-cron`) o el nombre `browser` traen los `browser_*` nativos y `browser_exec` (el Chromium del pod,
    sin pin): el servidor MCP se llama como el toolset nativo. La trampa que queda: un job de cron con `enabled_toolsets` propio no
    usa la lista y, sin un servidor MCP nombrado, recibe todos, `browser` incluido (cron/scheduler.py). Lo fija
    `tests/test_hermes_secretaria_navegador.py` resolviendo con `tests/fixtures/hermes/toolsets.py`, atada a la imagen por sha256
    e `image.tag`: al subir la imagen se vuelve a copiar.
  Y para la tarjeta de correo de las secretarias (INFRA-641/644, plugin `enviar`):
  - **Gmail por AgentGateway `/workspace`** (`gmail_get_draft`, `gmail_get_thread`, `gmail_get_message` y `gmail_list_labels` de
    lectura; `gmail_send_draft` y `gmail_delete_draft` de escritura), con `user_google_email` SIEMPRE explícito (omitirlo sirve la
    primera cuenta del binding). La LECTURA va por el listener PROPIO de cada perfil (8791-8795, `mcp.proxy.perfiles`): su
    binding en `backends/workspace/identity-bindings.yaml` acota qué cuentas lee, y esa es la valla de cuentas. El ENVÍO y el
    borrado solo por el listener `enviar` (8796) del client Keycloak `hermes-enviar` (roles `agentgateway-read:workspace` +
    `agentgateway-write:workspace-envio`, `forbiddenRole: agentgateway-write`, binding con las cinco cuentas; el rol
    `workspace-envio` y `gmail_get_draft` los crea INFRA-642 en `k8s-agentgateway-pocharlies`). Su `client_secret`: 1Password
    `hermes-kc-enviar` → ExternalSecret `hermes-kc-enviar` (`enviar.credencial.externalSecret: true` desde INFRA-644, 08-10: el item `hermes-kc-enviar` existe y su valor está cotejado con el client)
    → Secret `hermes-kc-enviar` montado en `/seed-secrets/kc-enviar` **solo en el contenedor `agentgateway-auth-proxy`**
    (`optional: true`: sin él el listener da 502 y no se envía nada).
  - **Estado durable**: SQLite stdlib en `/opt/data/enviar/estado.sqlite` (PVC del pod, directorio 0700, WAL, `PRAGMA user_version`),
    solo punteros y hashes (`draft_id`, ids de Gmail y de Telegram, sha256, nonce, plazos): NUNCA texto del correo ni del borrador.
    Excepción razonada a «los plugins no guardan estado» y a «SQLite a mano» de hermes-inbox.
  - **Webhook nativo del pod** (HMAC V2, `comun.pedir_turno`, la puerta de `empresa.delegar`) para pedir un turno a la secretaria
    ([Rehacer borrador], [Reintentar], [Pedir la tarjeta otra vez]).
  Y para las rutas del aviso de correo `gmail-*` (INFRA-631, P8 de INFRA-478): el item 1Password `hermes-webhook-gmail`
  (campo `webhook_secret`) → ExternalSecret homónimo (`templates/webhook.yaml`, forma Connect del store
  `onepassword-connect`, `refreshPolicy: OnChange`) → Secret `hermes-webhook-gmail` montado en `/seed-secrets/webhook-gmail`
  (volumen `seed-secret-webhook-gmail`, `optional: true`: sin él el seed no emite esas rutas). **El item debe existir ANTES de
  mergear**: con un ExternalSecret del ns en `SecretSyncedError`, ArgoCD lo juzga Degraded y `hermes-despliegue`
  (`preverificar`) aborta este despliegue y todos los siguientes de Hermes hasta que el item exista.
- **Dependen de él** — la **compañía entera** (los cuatro perfiles son los CTO/analista/sre-devops/security: hablan con las personas y verifican; las sesiones las lanza el supervisor desde SC-2213 y a Hermes solo le llega la `EXCEPCIÓN ·` del contrato `supervisor.orquesta.excepcion` de x86-host-runtime, SC-2214),
  `x86-host-runtime-pocharlies` (`hermes-despliegue` en `~/.local/libexec/x86-host-runtime/`), el dashboard (`dgx-studio-bot`
  en modo solo-avisos, `telegram_notify` e `incident_notify`: desde dgx-infra#918 envían con el token del bot de siempre,
  ExternalSecret `dgx-dashboard-telegram-bot`, al grupo «DGX Studio» o al chat/topic del `notify` del trabajo, solo a
  destinos de `TELEGRAM_NOTIFY_ALLOWED_CHATS`). La web `/studio` y la app iOS hablan con `/p/studio/` (dgx-infra#919).
  Las **rutas de webhook** (`/p/<perfil>/webhooks/<ruta>`, HMAC V2) las consumen tres manos: el supervisor del x86
  (`ENCARGO:`), monitoring y —desde 04-10-2026— el plugin `empresa` del propio pod (`delegar`, loopback). Ninguna de las
  tres abre puertas nuevas: las rutas son las de `webhook.routes`, y `empresa.permisos` acota qué perfil puede encargar
  a cuál (las de `analista`, `sre-devops` y `security` corren con `terminal`, `file` y Jira dentro del pod; `studio`
  también lleva `terminal`, `file`, `code_execution`, `browser` y `delegation` desde SC-1881, con `frenos: secretaria`).
  `docs/runtime-contracts.md` fija los contratos del runtime.
  Y el adapter de correo `synapse-adapter-gmail` (namespace `synapse`, INFRA-631): entrega el aviso clasificado a las cinco
  rutas `gmail-{dani,leila,casa,it,skirmshop}` (contrato `http.webhook.hermes_gmail_notify`: publisher aquí, en
  `CONTRACTS.yaml`; consumer en `synapse`, synapse#233), con el secreto HMAC propio de esas rutas
  (`HERMES_WEBHOOK_SECRET_GMAIL`, distinto del global) y es el único pod del namespace admitido en el puerto 8644 por
  `webhook.allowPods` (allow de red a nivel de pod, no de namespace). Renombrar una ruta `gmail-*` sin migrar al adapter
  rompe el aviso (404 y reintento del loop).
  Los **relés del dashboard** (`dgx-infra`: el Despacho de los cuatro perfiles en `routes_despacho.py`, y Jarvis/reloj en
  `routes_hermes_voice.py`) hablan con `POST /api/sessions/{id}/chat/stream`: un turno sobrevive al relé y la sesión da
  409 `session_busy` mientras vive (hermes-agent#7). El Despacho lo entiende desde dgx-infra#914 (avisa y el escalado
  reintenta); Jarvis/reloj (`routes_hermes_voice._ask`) lo devuelven tal cual como error 409.
  Y el contrato `hermes.inbox.messages.v1` (plugin `hermes-inbox`, INFRA-356): lo **consumen** el dashboard (`dgx-dashboard-backend` y
  `dgx-dashboard-worker`, fuente `dashboard`, INFRA-357), la compañía (`compania`) y Synapse (`synapse`); cada uno con su clave
  (`hermes-api-key-inbox-<fuente>`), ver `docs/hermes-inbox.md`. En red, el 8642 solo admite de `synapse` al pod `app.kubernetes.io/name: synapse-adapter-gmail` (`apiServer.allowFrom`, INFRA-651; nunca `part-of: synapse`).
  Y `company-roles` (agente `company-secretaria`, SC-1582): **produce** `pago-pendiente/v1` (deja la pantalla de pago
  abierta y el adjunto en la Acción) y deja el `pago-hecho/v1` que escribe el plugin como comprobante. Ningún código
  de `company-roles`, `x86-host-runtime` ni `dgx-infra` lo lee (`git grep "pago-hecho\|pago_hecho"` en
  `company-roles@main`, `x86-host-runtime@main` y `dgx-infra@master`: 0 resultados, 07-10-2026): solo lo RELEE el propio
  plugin (`ya_pagado()`, freno del doble pago) y lo leen como texto las personas y roles que auditan la Acción.
  Y `company-roles` (carpeta `skills/`, SC-2204): el seed **trae por ssh** del x86 las skills de la compañía que declara cada perfil
  (`profiles.<perfil>.companySkills`; el default, `gateway.companySkills` → `HERMES_COMPANY_SKILLS`) con la clave del PVC (`/data/ssh/`) y
  las instala en `<HERMES_HOME>/skills-compania/<huella>/`; el texto no se copia al chart. Con el x86 sin respuesta el seed no falla y deja la huella que hubiera.
- **ArgoCD**: repo `pocharlies-org/k8s-openclaw-qwen36-pocharlies`, path `helm/hermes`, tronco **`deploy/prod`**
  (`origin/deploy/prod` = 8bd5e90), namespace `hermes`. Una app: `hermes` (manual). `hermes-studio` se retiró el 02-10 (k8s-gitops#485).

## 3. Stack

| pieza | versión | para qué | no se usa en su lugar |
|---|---|---|---|
| Helm chart `helm/hermes` (+ `files/`, `templates/`) | 0.1.0 | Hermes | Kustomize |
| Imagen `hermes-agent` (fork público) | `fork-f24a9c7-p3426968` (overlays: `api_server.py` #7 + pool de turnos DGX-586, `homeassistant_tool.py` #10, rutas de perfiles retirados #11, `x-litellm-session-id` DGX-578, `webhook.py` #14 `rate_limit` por ruta INFRA-697) | gateway (arreglo `/reasoning` pendiente de fusión, SC-710) | upstream sin parche |
| Sidecar `hermes-reseed` | — | resiembra perfiles/SOUL/skills en caliente (~1 min) | reinicio del pod |
| Plugin `recarga-rutas` | — | recarga rutas de webhook | reinicio |
| Plugin `confirmar-pago` | — | compuerta de pago (SC-1584): dos botones en el topic «Pagos» del grupo Hogar (DGX-648) y un clic determinista tras el toque de Dani en ese chat e hilo; con `firma:"sca"` (SC-1697, transferencias) sin clic: vigila la pantalla hasta la firma de Dani en la app del banco | aprobaciones del núcleo (`approvals.mode` sigue `off`) |
| Plugin `enviar` | — | tarjeta de correo de las secretarias (INFRA-641/644): `tarjeta_correo` pone en el topic la notificación del correo y la tarjeta del borrador real de Gmail; **solo el segundo toque del aprobador envía**, con el `draft_id` atado a un nonce. SQLite stdlib en el PVC, un vigilante por proceso (cada 120 s), hook `pre_gateway_dispatch` para las respuestas forzadas | las aprobaciones del núcleo, un envío desde el modelo, estado en Postgres, `callback_data` con cuenta y `draft_id` |
| Plugin `hermes-inbox` | — | mensajes entrantes a sesiones (INFRA-356): `POST /api/inbox/messages`, contrato `hermes.inbox.messages.v1`; `aiohttp` 3.14.3 (la del fork) solo en CI, con hashes. Opciones de envío `silent`, `no_link_preview` y `prefix_own_line` (INFRA-662): el envío va por una copia superficial del adaptador de Telegram con `_notifications_mode` y `_disable_link_previews` forzados, así que **depende de esos dos atributos PRIVADOS del fork @f24a9c7** (502 si faltan o el bot no está conectado); salida limpia en INFRA-667 | SQLite a mano, `bot.send_message` directo, un endpoint en el fork |
| Plugin `empresa` | — | `delegar(destino, mensaje)`: un empleado encarga a otro lo que no es suyo (04-10-2026). Entrega por la ruta webhook nativa del pod, HMAC V2 firmado por el propio plugin. Desde DGX-657 (07-10-2026) también dos ganchos, `pre_llm_call` y `pre_tool_call`: `delegar` pregunta antes de entregar y nada se escribe con la cuenta de una persona a un bot o a un chat de empleados (gate y freno, §8) | que el SOUL enseñe curl+secreto, un bus nuevo, un filtro en AgentGateway (alcanzaría también a las sesiones de Claude de Dani, que sí escriben como él) |
| Python + pytest (tests de contrato) | CI hash-pinned | validación del chart | — |

## 4. Componentes compartidos

| concepto | pieza canónica | ruta | quién la usa |
|---|---|---|---|
| Config de Hermes | ConfigMap `hermes-config` (`seed-env.json`, rutas webhook JSON, `/seed-secrets`) | `helm/hermes/files`, `values.yaml` | todos los perfiles |
| Compuerta de pago | plugin `confirmar-pago` (contrato del artefacto `pago-pendiente/v1` en `docs/runtime-contracts.md`). **Componente canónico del destino de los avisos** (DGX-648): `pagos.chatId/threadId` de `values.yaml` → env `CONFIRMAR_PAGO_CHAT_ID/THREAD_ID` → `destino()` del plugin, que fija a la vez adónde se manda y de dónde vale un toque. Hermano: `libexec/pago-alerta` (x86-host-runtime) replica el destino por entorno (`PAGOS_TELEGRAM_CHAT/THREAD`) | `helm/hermes/files/plugins/confirmar-pago` | perfiles `secretaria*` (y quien la habilite en `values.yaml` → `pagos.perfiles`); el `default` solo cablea el handler |
| Guardas de Telegram, cliente MCP y puente al bucle del bot | `plugins/_comun/comun.py` (`mismo_entero`/`es_aprobador`/`donde`/`en_destino`/`Destino`, `ClienteMCP`, `en_bucle`, `pedir_turno`). Fuente única: el chart la sirve como `plugin-comun.py` (bajo `pagos.enabled` O `enviar.enabled`) y `hermes_seed.py` la copia como `comun.py` junto a cada plugin que la usa (`PLUGINS_CON_COMUN`); el plugin la carga con `from . import comun` (el gestor carga el directorio como paquete) o, sin paquete padre, del repo | `helm/hermes/files/plugins/_comun/comun.py` | `confirmar-pago` (reexporta los nombres de siempre) y `enviar` |
| Tarjeta de correo y envío con aprobación | plugin `enviar` (`tarjeta_correo`, `env:<nonce>:<a>`, SQLite). Su configuración, `enviar.json`, se DERIVA de values en `templates/_enviar.tpl` y se monta en `/etc/hermes-enviar` (releída en cada uso): destino de `webhook.routes.<perfil>.deliver_extra` (Acciones y conversación) y topic «Correo» de `enviar.correoHilo` (avisos y tarjetas; sin clave, el mismo; DGX-746), aprobador POR PERFIL de `enviar.aprobadores` (cada id se comprueba al renderizar contra `telegram.allowedUsers`, y el de Dani contra `pagos.aprobadorTelegramId`), puerto de lectura de `mcp.proxy.perfiles` | `helm/hermes/files/plugins/enviar`, `values.yaml` → `enviar` | perfiles `secretaria*` (los cinco); el `default` solo cablea el botón y el hook |
| Aviso del Studio en el topic de la petición | hook `pre_tool_call` del plugin `dgx-studio` (`_on_pre_tool_call`): fija `notify` {custom, grupo, topic} en `studio_generate_*` | `helm/hermes/files/plugins/dgx-studio/__init__.py`, `values.yaml` → `studioPlugin` | perfil `studio` (y el default, que también lleva el plugin) |
| Home Assistant por perfil | `hass_env()`: `HASS_URL`/`HASS_TOKEN` solo en el `.env` de `homeAssistant.perfiles` | `helm/hermes/files/hermes_seed.py`, `values.yaml` → `homeAssistant` | `jarvis` (INFRA-411); ruta de webhook `jarvis-aviso` |
| Mensajes entrantes a sesiones | plugin `hermes-inbox` (contrato `hermes.inbox.messages.v1`, `CONTRACTS.yaml`, `docs/hermes-inbox.md`) | `helm/hermes/files/plugins/hermes-inbox`, `values.yaml` → `hermesInbox` | dashboard (INFRA-357, fuente `dashboard`), compañía (`compania`), Synapse (`synapse`) |
| Delegación entre empleados | plugin `empresa` → herramienta `delegar` (única forma contada de encargar algo a un compañero; **frescura: en caliente, sin reinicio** — `empresa.json` y `webhook_subscriptions.json` se releen en cada llamada a `delegar` y el receptor relee sus rutas por petición, así que `destinos`, `permisos`, `delegar`, `freno` y `webhook.routes` aplican al llegar la resiembra; medido 06-10-2026, SC-1950: 0 reinicios de contenedor tras el merge de #542. Al contrario que el bloque global `telegram:`, que es snapshot de arranque, SC-1909. **El CÓDIGO del plugin no es caliente**: el gateway importa un plugin una vez por proceso y el Deployment no lleva checksum del plugin, así que fusionar un cambio de `__init__.py` no lo carga; entra con el reinicio ordenado de `hermes-despliegue.yml` (`accion=reiniciar`) y la prueba de que el código vivo es el nuevo es la línea `empresa: gate y freno activos en el perfil X` en el log de cada perfil) | `helm/hermes/files/plugins/empresa`, `values.yaml` → `empresa` (`destinos` = rutas de `webhook.routes`; `permisos` = matriz default-deny que fija security; `delegar` = qué turnos son de máquina y no preguntan; `freno` = las listas de las cuentas de persona, con `canal`, `chats_empleados` y `excepciones` generados por la plantilla `hermes.empresaFreno` en `templates/_helpers.tpl`) | todos los perfiles enrutados y el default; el secreto HMAC lo toma del `webhook_subscriptions.json` del home |
| Pregunta antes de delegar y freno a las cuentas de persona (DGX-657) | **componente canónico**: `helm/hermes/files/plugins/empresa/__init__.py` (`_gate`, `_freno_veto`), con su config en `values.yaml` → `empresa.delegar` y `empresa.freno`. Las listas las firmó security (P0b, 07-10); `chats_empleados` es `telegram.groupAllowedChats` y `excepciones` son las rutas `webhook.routes.secretaria*`, ambas generadas, con test que fija la igualdad | `helm/hermes/files/plugins/empresa`, `values.yaml`, `templates/_helpers.tpl`, `tests/test_hermes_empresa_gate_freno.py` | los catorce perfiles, el default y los perfiles servidos que el chart no declara (`culturismo`: `hermes_seed.py` `PLUGINS_AJENOS`). El freno vale donde corre el plugin; un test exige que TODO perfil servido con el MCP `social`, mirado en disco tras sembrar y no en una lista de `values.yaml`, lo cargue |
| Señal de cierre del turno (SC-1987 P3) | `company-sesion cerrar --estado resuelta\|espera\|pregunta\|para-dani [--espera …] [--motivo …]`: la señal va en los argumentos y el texto para la persona sin etiquetas; `PARA DANI:` literal solo en el Despacho (`dgx.cto.despacho.v1`) y en las Acciones. Ejemplo de buen cierre en `lenguaje` | `values.yaml` → `herencia.bloques.turno-corto` (gramática) y `lenguaje` (ejemplo); consumidor: `libexec/company_encargos.py` de x86-host-runtime | los cuatro perfiles con `company-sesion` (cto, analista, sre-devops, security); `lenguaje` en los catorce |
| Reparto de la empresa (texto que leen los empleados) | bloque heredado `herencia.bloques.org` — una sola verdad: ningún SOUL lo repite | `values.yaml` → `herencia` (`bloques` + `hereda`), `hermes_seed.py` `soul()` | todos los SOUL sembrados (`org`; `oficio-secretaria` en las cinco secretarias; `recibir-encargo` en los destinos); `org` también enseña cuándo algo sube a Dani: regla en llano de cuándo sube algo a Dani (dinero, irreversible, mano), SC-1986) |
| Herencia de bloques de texto (quién hereda qué y su techo) | `herencia.bloques` + `herencia.hereda`: `org` y `lenguaje` los catorce perfiles (`_todos`); `turno-corto` y `responder-dani` (qué hacer con lo que Dani contesta, SC-2265) analista, sre-devops, security y cto; `recibir-encargo` las secretarias, analista, sre-devops, security y studio; `oficio-secretaria` las cinco secretarias; `navegador-secretaria` las cuatro que cargan `browser` (DGX-760; aparte porque `oficio-secretaria` está pegado a su techo; baseline 150 y techo 158 en `tests/fixtures/hermes_soul_baseline.json`); `norma-navegador` los cuatro que navegan. Techos: `org` + `lenguaje` + `turno-corto` ≤ `techo_trio` (670 palabras); `recibir-encargo` ≤ `techo_recibir_encargo` (114, cabecera literal); `oficio-secretaria` ≤ `techo_oficio_ratio` (75 %) de su baseline (987 → 738; el párrafo «Dinero… Pagos.» y la cadena PATRÓN FIJO, 430 palabras, van literales y los fija `tests/test_hermes_oficio_dinero.py`, SC-2040); la medida de cada bloque antes de podar es referencia, no techo; todo en `tests/fixtures/hermes_soul_baseline.json` (`bloques`, `techo_trio`) y `tests/test_hermes_soul_tamano.py` | `values.yaml` → `herencia`, `hermes_seed.py` `soul()` | todos los SOUL sembrados |
| Identidad MCP por perfil | proxy multi-listener `mcp.proxy.perfiles` (un listener 127.0.0.1:8791-8796 —el 8796 es el de envío— y un client Keycloak por perfil de secretaria, cuyo `client_secret` llega por el Secret `hermes-kc-secretarias` montado como ficheros `/seed-secrets/kc/<perfil>/client_secret` solo en el contenedor del proxy; 8790 y su comportamiento intactos; `DENY_SECRETARIA` veta el rango `*879?*` para que el terminal de una no use el listener de otra; rotar un secreto exige force-sync del ExternalSecret + reinicio del pod — el proxy lee el fichero solo al arrancar). Ese proxy es también el componente del pin de `connection` de `/browser` (DGX-760, §2), probado en `helm/hermes/files/agentgateway-auth-proxy-perfiles.test.js`) | `helm/hermes/files/agentgateway-auth-proxy.js`, `values.yaml` → `mcp.proxy.perfiles`, `hermes_seed.py` `mcp_perfiles()`, `deployment.yaml` volumen `kc-secretarias` | perfiles `secretaria*`, las cinco en su puerto desde INFRA-494 (secretaria 8791, secretaria-dani 8792, secretaria-leila 8793, secretaria-casa 8794, secretaria-skirmshop 8795); los demás perfiles (`jarvis`, `studio`…) siguen en el 8790 compartido |
| Secreto HMAC por ruta del webhook (INFRA-631) | `secretRef: <VARIABLE>` en una ruta de `webhook.routes` → esa variable del seed (hoy `HERMES_WEBHOOK_SECRET_GMAIL`, declarada en `hermes.seedSecrets` desde `webhook.routeSecret` y leída de `/seed-secrets/webhook-gmail`) → `escribir_rutas_webhook()` firma la ruta con ella y no escribe `secretRef`; variable vacía = la ruta no se emite (falla cerrado); sin `secretRef` = secreto global. ExternalSecret `webhook.routeSecret.secretName` (forma Connect, `refreshPolicy: OnChange`) | `values.yaml` → `webhook.routes` y `webhook.routeSecret`, `hermes_seed.py` `escribir_rutas_webhook()`, `templates/_seed.tpl`, `templates/webhook.yaml`, `tests/test_hermes_webhook_gmail.py` | rutas `gmail-*` (contrato `http.webhook.hermes_gmail_notify`); `secretaria-*` y la compañía siguen con el global |
| Allow de red a nivel de pod del webhook (INFRA-631) | `webhook.allowPods` (`namespace` + `podLabels`, ambos obligatorios: sin etiquetas el render falla, porque un `podSelector` vacío admitiría el namespace entero) → una entrada `from` con `namespaceSelector` Y `podSelector` en `hermes-webhook-allow-x86`; `allowFrom` y `allowNamespaces` no cambian | `values.yaml` → `webhook.allowPods`, `templates/webhook.yaml` | `synapse-adapter-gmail` (namespace `synapse`, puerto 8644) |
| Pipeline de despliegue | `hermes-despliegue.yml` + `hermes-despliegue` (x86-host-runtime) | `.github/workflows/` | únicamente Hermes |
| Validación | `scripts/validate.sh` | ídem | `validate-pr.yml` |
| Runbooks | `docs/hermes-e2e-runbook.md`, `hermes-cutover.md` | `docs/` | operación |

## 5. Cómo se construye aquí

Perfiles, rutas, SOULs, skills, keys y variables se cambian por **PR + merge, sin reinicio**: el sidecar `hermes-reseed` re-siembra en ~1 min y
Hermes relee perfiles, `config.yaml` y el `.env` de cada perfil. Solo reinician la imagen, los recursos, los puertos del pod
y `mcp.proxy.perfiles` (el proxy lo lee solo al arra