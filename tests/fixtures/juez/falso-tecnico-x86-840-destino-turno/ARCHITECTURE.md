# ARCHITECTURE — x86-host-runtime-pocharlies

Resumen de arquitectura del runtime de agentes del host x86 (nodo k8s `ubuntu`).
Ampliado desde el README (la referencia operativa) y la nota del architect de DGX-449.

## Que es este repo

El inventario versionado de lo que corre como **`systemd --user` en x86**: unidades,
scripts de host, hooks del brain y skills. No es Kubernetes: no hay ArgoCD ni Helm
aquí. El despliegue es `./install.sh` ejecutado en el x86 (lanzado por su CI), que
copia y reinicia solo lo que cambió.

## Clientes (quien consume esto)

- **Las sesiones de Claude/opencode del operador**: `claude-rc-*` (Remote Control),
  `opencode-web` + `openchamber` (las dos UIs comparten proceso).
- **El panel DGX (control-nexus)**: consume `claude-rc-status` (`/company-view`,
  `/company-options`, `/company-live`) y `claude-rc-bridge` (`/api/rc/...`), espejados
  1:1 bajo `/api/rc/...` sin tocar el disco del host.
- **Jira (Forge AIOPS)**: `jira-forge-push` le empuja estado firmado HMAC;
  `jira-epic-trigger` recibe su webhook.
- **La compañía (Hermes + sesiones CLI)**: `company-*` (agent, buzón, métrica,
  frenos, options-applier) y el supervisor.
- **La extensión de Claude Code en VS Code (Remote-SSH al x86, SC-1973)**: ejecuta `libexec/claude-con-cuenta.sh`
  como `claudeCode.claudeProcessWrapper` en cada arranque de `claude` y muestra `vscode-claude-cuenta/` (barra de estado).
  Las sesiones de terminal y `claude-tmux` no eligen cuenta (solo les afecta no heredar el token ni el directorio de credenciales). La vista lateral «Cuentas»
  (DGX-640, 1.4.0) la PINTA la propia extensión (webview nativo, sin iframe): el webview se dibuja en el Mac (Remote-SSH) o en el
  propio Mac (`mac-cb`, SC-2086) y la extensión, que corre en el x86 o en ese Mac, lee las cuotas del dashboard.
- **El VS Code LOCAL del Mac de CloudBlue (`mac-cb`, SC-2086)**: sin Remote-SSH, sin MDM, con su propio `~/.claude`. Es OTRO cliente de
  `vscode-claude-cuenta/` y de `libexec/claude-con-cuenta.sh` (1.3.0 con `claudeCuenta.cuentasJson`), distinto de `Host mac`, el
  Mac de Dani que sirve a `agent-browser-sync.sh`. Lo deja instalado y al día `libexec/claude-cuenta-mac.py` desde el x86.
- **El brain**: los alimentadores `libexec/brain-sweep.sh` (cron `*/5`) y
  `libexec/brain-opencode-sync.py` (timer): ingesta de transcripts y digeros opencode.

## designer-plugin/ (INFRA-397)

Skills de diseño web vendorizadas del diseñador (plugin de Claude Code; `LOCK.json` fija repo, commit,
licencia y sha256 por fichero). `install.sh` lo copia a `~/.local/share/x86-host-runtime/designer-plugin/`;
solo `design-request.py` lo carga (`--plugin-dir`, INFRA-398). NO va en `skills/` ni en `~/.claude/skills`
(global). Test: `ci/test_design_skills.py`.

## Componente canónico: el turno de candidatos del blog (INFRA-222)

[DECISION: x86-host-runtime-pocharlies: el componente canónico del turno del blog es libexec/blog-daily.py con la lógica en libexec/blog_candidatos.py y los prompts en libexec/blog_prompts.py; la política y el catálogo viven en k8s-blog-pocharlies (src/site/politica/, leídos de origin/main con git show) y el estado mutable en ~/.local/share/blog-daily/registro.json]

`blog-daily.py` elige un candidato del catálogo del blog, pide tres veredictos schema v1 (el modo de marketing lo fija
la invocación, no un campo del JSON), redacta, pide la pieza a `company-designer` y deja UN commit a `drafts`;
`blog-approve.py` publica la pieza con el post y marca el candidato en el registro. Test: `ci/test_blog_candidatos.py`
y `ci/test_blog_bilingue.py` (herméticos). Depende de `k8s-blog-pocharlies` (política y shortcode `pieza`); el contrato
tema ↔ pieza (`pieza:ready` v1, fuentes en `/fonts/`) es del blog.
Seguridad (nota-architect-pr635): la pieza y los textos los escribe un modelo. `blog_candidatos.inspeccionar_arbol` rechaza
symlinks, hardlinks y rutas fuera de la carpeta (también en `--draft`), `validar_pieza` aplica `EXTERNO_RE` y `es_privado`
a cada fichero de texto, y los textos ES/EN pasan por `es_privado` antes del commit. `es_privado` vive en
`blog_candidatos.py`; la única excepción son los `nombres_publicos` del candidato (catálogo del blog), solo para la regla
de negocio de terceros. La válvula de 48 h llama a `descartar` de blog-approve en proceso (el turno ya tiene el Lock).

Pie de la pieza (INFRA-225): `{{< pieza "<fecha>-<slug>" "pie" >}}` con segundo argumento opcional; `asegurar_shortcode` solo cambia el slug y deja
un único shortcode bien formado (también si un modelo lo rompió). Contrato con el blog: el shortcode acepta ese segundo argumento (PR #17/#19 de
k8s-blog-pocharlies). Un `error` con borrador ya empujado y sin `message_id` se reenvía (`reenviar_aviso`) y no se regenera.

## Componente canónico: ingesta al brain

[DECISION: x86-host-runtime-pocharlies: el componente canónico de la ingesta de transcripts y digeros opencode al brain es libexec/brain-sweep.sh y libexec/brain-opencode-sync.py; su estado vive en ~/.local/share/brain-sync/state]

## Componente canónico: lista semanal de Backlog parado (SC-1765)

[DECISION: x86-host-runtime-pocharlies: el componente canónico de la lista semanal de Backlog parado es libexec/backlog-parado.py; la entrega a las secretarias sigue siendo ~/.claude/skills/secretaria/scripts/secretaria.sh]

`backlog-parado.py` lee Jira en solo lectura (cliente `jira_rest.py`, identidad del supervisor, solo
GET) e importa `jira-epic-trigger.py` tal cual por `importlib` (ruta vía `JIRA_EPIC_TRIGGER`,
precedente `libexec/vigilante.py:98`); los bloqueos los dicta `company_control.blocks_entrantes`.
Los motivos viven en Jira (changelog, etiquetas, spec) y en el plan del supervisor: nada de estado
local propio. La entrega la dispara `units/backlog-parado.timer` (lunes 08:30, `Persistent=true`)
y la hace `secretaria.sh` — el rc del subprocess es el criterio (0 solo con HTTP 200/202).

## Componente canónico: pago-alerta (aviso de pago, DGX-648)

[DECISION: x86-host-runtime-pocharlies: el componente canónico del aviso de pago antes de la firma (Jira, dashboard, app DGX y Telegram) es libexec/pago-alerta, con su skill en skills/pago-alerta; su destino de Telegram (PAGOS_TELEGRAM_CHAT y PAGOS_TELEGRAM_THREAD) replica por entorno el destino canónico de k8s-openclaw-qwen36-pocharlies, pagos.chatId/threadId en helm/hermes/values.yaml y destino() en helm/hermes/files/plugins/confirmar-pago/__init__.py]

`pago-alerta enviar` lo lanzan las secretarias (skill `pago-alerta`) y es determinista, sin modelo: comentario con la captura
en la Acción de Jira (`jira_rest.py`, cuenta del rol en `JIRA_ROL`), pago en el dashboard, push APNs a la app DGX y Telegram.
Corre en el x86 (no en el clúster) porque necesita `kubectl` para leer sus secretos; no tiene unidad ni estado propio.

- **Dependencias reales**: Secret `control-nexus/dgx-dashboard-pagos` (HMAC del dashboard, `/api/pagos`, `/esperar` y `/resultado`),
  Secret `hermes/hermes-secrets` clave `TELEGRAM_BOT_TOKEN` (el bot de Hermes, por `kubectl`; el token va a un fichero `-K` de
  `curl`, nunca a los argumentos), la clave APNs `~/.config/pagos/AuthKey_<id>.p8` y `jira_rest.py` de este repo.
- **Destino de Telegram (DGX-648)**: el topic «Pagos» del grupo Hogar. `PAGOS_TELEGRAM_CHAT` y `PAGOS_TELEGRAM_THREAD`
  (con sus valores por defecto en el script) se validan por regex antes de llamar a `curl`: un destino ilegible no manda
  nada, y no existe rama «sin hilo» ni vuelta al privado de Dani (eso sería una decisión de despliegue). Si cambia el topic,
  cambia también `pagos.chatId/threadId` del chart de Hermes, y al revés: son la misma decisión en dos repos.
- **Contrato del mensaje**: `sendPhoto`/`sendMessage` con `message_thread_id` y `protect_content=true`; la entrega se comprueba
  (`result.chat.id` y `result.message_thread_id`, enteros estrictos) y, si llegó a otro sitio, `deleteMessage` y fallo.
  El texto de Telegram va enmascarado (IBAN, cuenta de cargo, URL con solo el host y barrido de IBAN sueltos; un IBAN
  español es ES + 2 + 20 dígitos exactos, y el de otro país solo si su longitud y su control mod-97 cuadran, para no
  mutilar importes ni referencias); Jira y la app conservan el detalle completo. La captura del banco no se enmascara: la audiencia del grupo la aceptó `security` (DGX-648 C6).
- Tests: `ci/test_pago_alerta.py` (herméticos: `curl` y `kubectl` simulados, sin red ni Telegram).

## Componente canónico: el bucle de aprendizaje de skills (SC-1974)

[DECISION: x86-host-runtime-pocharlies: el componente canónico del bucle de aprendizaje de skills es libexec/company_aprender.py (conteo, estado, cola, lanzamiento), su control determinista libexec/company_aprender_control.py y la apertura de PR de candidatas al catálogo libexec/catalogo_pr.py (también la usa el exportador de SC-1820 P6)]

[DECISION: opencode-company: la clave aprendizaje de roles.json declara modo, cadencia, límites y los roles activos; la lista de skills protegidas NO está ahí, está en skills/_protegidas.yaml del catálogo]

Un rol activo que suma `aprendizaje.cadencia` iteraciones de herramientas dispara una revisión en segundo plano: un
`claude -p --agent company-learner` lee un extracto redactado de lo que hizo y, si hay una técnica reutilizable con
evidencia, deja una propuesta. Las skills vivas no se tocan nunca; la candidata sale como PR en borrador al catálogo.

- **Contar** (`company_aprender.al_parar`, desde `libexec/company-aprender-hook.py`): `SubagentStop` en vivo (clave
  `agent-<id>`) y `Stop` en asíncrono (clave `session_id`), campos medidos en la sonda P0. Se cuentan los `message.id`
  distintos de asistente con `tool_use` (cada bloque es una línea con el mismo id). El estado lleva dos offsets: `contado`
  avanza en cada hook, `cursor` solo al terminar una revisión, con el offset de cuando se lanzó (A8). El hook
  sale 0 y sin salida siempre. El `Stop` de los arranques asíncronos sale de UNA función, `company_aprender.hooks_stop`.
  El censo de esos arranques lo fija `CensoDeArranques` en `ci/test_company_aprender.py`.
- **Enganche (P4), dos sitios a propósito**:
  - *En vivo*: `hooks.SubagentStop` en `~/.claude/settings.json`, escrito por `libexec/claude-aprender-hooks.py`
    (install.sh en cada despliegue y el applier cuando se mueve company-roles) con
    `claude_settings.asegurar_hook`. El matcher es `registro_roles.matcher_aprendizaje()`, ANCLADO
    (`^company-(…)(-reserva)?$`): el CLI casa por subcadena. Se instala también con `modo: off` (el hook no hace
    nada; encender es la PR de una línea), y solo si `company-aprender-hook.py` existe: un `SubagentStop` que sale
    con 2 no deja terminar al subagente.
  - *Asíncrono*: `hooks.Stop` en el `--settings` de cada arranque, por `company_aprender.settings_arranque(agente,
    base)` (sobre `hooks_stop`): `settings_sesion(…, agente)` de jira-epic-trigger (`_lanzar` en sus dos ramas,
    los dos arranques de `pm`) y, por ella, `company-claude`; blog-daily/approve, design-request y `claude_agente`.
    Rol sin bucle o `modo: off`: el mismo `--settings` de antes.
  - Por qué no un `Stop` en el settings compartido: costaría un proceso Python en CADA turno de las sesiones de
    Dani; el `SubagentStop` con matcher solo corre al acabar un subagente de un rol activo.
- **Lanzar**: unidad transitoria `systemd-run --user` con `COMPANY_APRENDIZ=1`, fuera del cgroup de la sesión (el bus
  para las `ses-*` ociosas). `revisar` toma el `flock` de un learner a la vez: el learner no está en el registro de
  sesiones y `trabajando()` no lo cuenta. Después mira el tope diario, el gancho de `prs_abiertas` y la admisión: las
  de `company-sesion.comprobar_hueco`, la cola del vLLM a 0 y, la última, `company_ritmo.tomar_hueco`. Si no cabe,
  la clave pasa a `cola/` con `aplazada`. Pasadas `aplazar_max_horas`, se descarta sin mover el cursor.
- **Lo que ve el learner** (D6, A3, A7c): `trabajo/<id>/` (0700), con los nombres del contrato de P1: `extracto.md`,
  `skills.txt`, `skills/<n>/SKILL.md`, `nombres.txt` y `propuesta/`. El extracto quita `thinking`, recorta las
  herramientas (300/400/800), redacta secretos con `libexec/antifugas.py` y cambia cada denegación del guard, junto
  con lo que la sigue hasta el siguiente éxito, por `[denegación del guard: no es aprendible]`. Lanzado por
  `libexec/claude_agente.py` con `--tools Read,Grep,Glob,Write`, `--strict-mcp-config`, `cwd` en su directorio y
  `PONYTAIL_DEFAULT_MODE=off`. El host lee solo el `propuesta/` de su propio `<id>`.
- **Costuras con P3**: `company_aprender.py` llama a `company_aprender_control.es_protegida` y `.protegidas`, a
  `catalogo_pr.nombres` y a `company_aprender_pr.entregar` y `.tope_prs` (P3, abajo). Sin ellos desplegados, todo cuenta
  como protegida y ninguna propuesta sale (`bloqueada`).
- **El control y la PR candidata (P3)**:
  - `libexec/company_aprender_control.py`: `revisar(borrador, catalogo, vivas, registro) -> (ok, motivos)`, pura,
    sin red ni LLM. Seis comprobaciones en orden: destino (solo `skills/<n>/SKILL.md` o `skills/_propuestas/<X>/<id>.md`,
    ≤ 3 ficheros y 250 líneas, `tools/validate_skills.py` del catálogo, y la propuesta la parsea el control porque el
    validador salta `_*`), protegidas (realpath, `skills/_protegidas.yaml` de `origin/main` del clon, nunca de la rama del
    learner, y ausente o ilegible ⇒ no hay PR), procedencia (la del hook: `estado: candidata`, `origen: claude`,
    `roles: [<rol>]`, `temas: []`, bloque `aprendida`; cualquier otra clave bloquea), puertas y firmas (texto normalizado
    sobre el fichero entero, líneas añadidas **y eliminadas** en un parche; tokens derivados de `jira_rest.py catalogo`,
    de los roles y de los ejecutables propios, más los fijos), borrado de reglas (`NUNCA`, `MUST`, `siempre`…) e higiene
    (Unicode invisible, `eval`/`sudo`/`rm -rf`, secretos con `libexec/antifugas.py`, sobre TODA la propuesta: el
    learner puede haber leído un secreto fuera del extracto). Riesgo residual declarado: una paráfrasis sin ningún
    token derivado; lo cubre la revisión de `security`. La puerta de verdad sigue siendo `jira_rest.py gate`.
  - `libexec/catalogo_pr.py`: `abrir_pr_candidata(nombre, ficheros, procedencia, titulo, cuerpo, borrador)` sobre un solo
    clon (`~/.local/share/x86-host-runtime/skills-catalog-clon/`, `flock`, una worktree y una rama por PR), con el
    envoltorio de `gh` y de la herramienta de control de versiones de `ci_recetas`. Crea la etiqueta `aprendida` y
    deduplica por nombre.
  - `libexec/company_aprender_pr.py`: construye los ficheros con la procedencia del hook y abre la PR (A1: título
    `aprendida: <nombre> (<rol>)`, rama `aprendida/<rol>-<sid8>-<aaaammdd>-<nombre>`, **sin clave de ticket**, en
    borrador y con la etiqueta; la clave de origen va en el cuerpo). **El host nunca ejecuta `gh pr ready` ni
    `gh pr merge`**: sin clave, `company-aprobar` responde «la PR no cita ningún ticket» y `jira_rest.prs_abiertas`
    no cuenta la candidata; la fusión es un acto humano tras el visto bueno de `security`. Un fallo de clon o de `gh`
    sube como `CatalogoError` (el bucle lo anota `fallo`), no como bloqueo.
  - **La Task del lote (A10)**: tras abrir una PR (`entregar` llama a `asegurar_lote`), UNA Task en SC con
    la etiqueta `aprendizaje-lote` (sin `it-request`, sin asignar), con la lista de PR; se reutiliza mientras esté
    abierta, se pone al día si cambia la lista y tras una búsqueda fallida no se crea nada. La recoge el lote semanal
    de `security` con Dani, igual que `rotacion-semanal`.
  - Tests: `ci/test_company_aprender_control.py` (fixtures F1-F12 y benignas en `ci/fixtures/aprender/control/`; incluye
    que un control vacío las deja pasar todas) y `ci/test_company_aprender_pr.py` (catálogo de pega como origin real,
    `gh` y Jira falsos).
- **Quién consume `catalogo_pr.py`**: el learner (por `company_aprender_pr`) y el exportador de SC-1820 P6, que la
  importa.
- **Excepción a K8s first**: el timer y las revisiones corren en el x86, no en un Job del clúster. El CLI, el router,
  la cuenta de la compañía y los transcripts solo existen aquí, y un Job tendría que recibir los transcripts por red,
  peor para la privacidad. `company-aprender.timer` es un oneshot cada 10 min con `ConditionDirectoryNotEmpty=` sobre
  `cola/`. No hay demonio, y nada corre en los Sparks: el único cliente LLM es `claude -p` por el router.
- **Registro** (A9): `registro.jsonl` sin contenido; `company_aprender.py estado` da el recuento de 24 h y la edad de
  la última revisión terminada; la pasada de la cola sale ≠ 0 con 3 `fallo` seguidos.
- Tests: `ci/test_company_aprender.py` (herméticos; la prueba viva del learner con Bash, con `APRENDER_PRUEBA_VIVA=1`).

## Caída de Jira/MCP (SC-1728)

[DECISION: x86-host-runtime-pocharlies: el componente canónico de la detección de caída de Jira/MCP y de su Request única es libexec/company_caida_jira.py (resumen estable en company_requests.RESUMEN_CAIDA_JIRA); la lectura por REST alternativa vive en jira_rest.buscar_issues/get_issue y se usa desde jira_search/jira_issue del trigger]

- **Lectura por REST (SC-1831)**: con el MCP caído, `jira_search` y `jira_issue` del trigger leen por
  `jira_rest.buscar_issues` / `jira_rest.get_issue` con la cuenta del supervisor (`jira_rest.como_supervisor`) y
  `jira_rest.plano` iguala la forma. Disyuntor por barrido: `Mcp.caido` (error literal del primer fallo). Las
  escrituras siguen por el MCP; no hay escritura REST alternativa.
- **Detector (SC-1832)**: `registrar_caida` (final de `barrido()`, también en los `return` anticipados) pasa
  `Mcp.caido` a `company_caida_jira.registrar`. State aditivo `st["caida_jira"] = {desde, barridos, error, request,
  ultimo_aviso}`; ausente = sin caída.
- **Umbral**: Request cuando `barridos >= CAIDA_JIRA_BARRIDOS` (2) Y `ahora - desde >= CAIDA_JIRA_MIN_S` (300 s).
  Cadencia medida del journal de `jira-epic-trigger` (24 h, 05-10-2026, 303 barridos): mediana 268 s, media 284 s,
  p10 190 s, p90 404 s, máx 609 s (≈4,5 min, no los 2,3 min supuestos) → N=2; la Request sale en el primer barrido
  que pasa de 5 min (≈5-9 min).
- **Request única**: antes de crear, `company_requests.buscar_caida_abierta()` (REST); si hay abierta se comenta en la
  más antigua y no se crea; nunca se crea tras una búsqueda fallida. Con la Request abierta, un comentario cada
  `CAIDA_JIRA_AVISO_S` (1800 s); al volver el MCP, UN comentario «recuperado» y se borra el state. La cierra el
  Operador IT.
- **Segunda detección (SC-1835)**: `ops-watch._request_de_incidente` aplica el mismo dedup para el incidente de Keep
  cuya regla está en `company_requests.REGLAS_CAIDA_JIRA` (= `AtlassianMcpToolDown`, la VMRule de
  k8s-observability-pocharlies sobre la sonda de SC-1834): comenta la Request única en vez de abrir una por
  incidente, y si crea, el resumen empieza por `RESUMEN_CAIDA_JIRA`. La carrera con el supervisor es de segundos
  y aceptada (ambos comentan en la más antigua); no hay lock distribuido.
- **El resumen es un contrato**: `company_requests.RESUMEN_CAIDA_JIRA = "[IT] Jira/MCP de Atlassian no contesta"`
  (sin hora ni clave); quien busca la Request (supervisor, `ops-watch`, SC-1835) lo hace por él. Cambiarlo = una
  constante nueva junto a la vieja, no editarla.
- **Encargo al Operador IT (SC-1833)**: `brief_de_request` elige `company_caida_jira.brief_caida_jira` cuando el
  resumen empieza por `RESUMEN_CAIDA_JIRA`. Lleva el error literal, el inicio, los barridos, `MCP_URL` y la
  comprobación (la descripción de la Request) y manda todo por `jira_rest.py` (`get|comments|comment|progreso|
  transicion … Done --rol it`); nunca los `jira_*` del MCP. Con `ATLASSIAN_MCP_URL` roto, `comments` y `estado` siguen
  saliendo con 0 (probado con `http://127.0.0.1:1`).
- **Prueba end-to-end (SC-1836)**: `ci/stub-mcp-500.py` (`--modo 500|ok|colgado`, cambio en caliente por `--control`) y
  `ci/prueba-caida-jira.py` (la repite qa): barre con el trigger instalado, un `STATE_DIR` y unas opciones de prueba y el stub
  como `ATLASSIAN_MCP_URL`; nunca el state, el MCP ni la unidad de producción. Lo único real es la Request en Jira, que adopta
  el trigger de producción y cierra el Operador IT (límite conocido). El barrido va aislado (`entorno()`: HOME propio, bots/sesiones
  en un tmp, `systemctl` de mentira, state con `llm_saturado`). Tests herméticos: `ci/test_stub_mcp_500.py`, `ci/test_prueba_caida_jira.py`.

## Componente canónico: freno de Requests IT/Security (SC-1977)

[DECISION: x86-host-runtime-pocharlies: el componente canónico del freno de las Requests IT/Security es libexec/jira-epic-trigger.py (sin_novedad, pausa_por_bucle, orden_requests) y la huella de la situación de la Request libexec/company_huella.py (componentes, cambios; SC-1985), sobre el ledger libexec/company_encargos.py (ultimo_cierre, marcar_espera_externa, marcar_huella); el supervisor es el único que crea encargos de Request (company_bus.a_bot no los crea); el cupo en que compiten las Requests y las épicas es la tope_dinamico del barrido, sin otra fuente]

Un encargo nuevo a una Request exige algo nuevo desde el cierre del anterior: evidencia (`evidencia_nueva`, comentarios de fuera, sin los de la
casa), un cambio de la huella (`company_huella`: estado de Jira, adjuntos con su cuenta —sin los de la cuenta del propio rol, `supervisor` ni
`cto`— y estado de las PRs citadas) o `respuesta_operador`; o el plazo único `SIN_NOVEDAD_PLAZO_S` de 24 h (si el turno cerró con
`ESPERA: fecha`/`PARA DANI:`, la Request se aparca sola con `parked-hasta-<ISO>`). Sin novedad el barrido dice «sin novedad desde HH:MMZ, no se
reencarga». La base de la huella (`huella_sit` en el ledger, por id de encargo) se toma en el PRIMER barrido tras el cierre, no al despachar:
lo que el bot hace en su turno no es novedad (la que llegue entre el cierre y ese barrido, ≤ 4,5 min, se absorbe en la base; los comentarios no
se pierden: van por marca de tiempo). Una lectura de Jira o `gh` que falla conserva el valor de la base: un fallo no es un cambio. El encargo
lleva lo que cambió (`rq["novedad"]`, `bloque_novedad`). Solo cubre Requests de bots it/security; la épica del bot `cto` no.
`parked-hasta-<ISO>`, Hold y «asignada a Dani» valen para toda Request (`request_parada`), también la del bot. Las Requests van delante de las
épicas (SC-2162, Dani 09-10) y cogen cualquier plaza libre del cupo común (los encargos en marcha cuentan,
`bot_en_marcha`; las épicas con su encargo al bot cto en marcha o esperando hueco también, desde el principio del barrido: `activas_cto_de`, SC-2248; y reanudar una Request pide plaza como lanzarla); mientras una espere por falta de plaza no entra ni se reanuda ninguna épica que no trabaje ya. Entre ellas manda
`orden_requests`, no la llegada: `prioridad-dani` o Highest, las que bloquean a otro ticket, las empezadas y el resto, cada grupo por
el `created` de Jira (`requests_abiertas` pide `priority` e `issuelinks`; `anotar_orden` lo guarda en `rq["orden"]` en cada barrido) y
`st["en_cola_it"]` sale en ese orden; tope diario `REQUEST_MAX_DIA` (6) que solo la respuesta de Dani salta. Una [SEC] abierta por ticket origen (`company_bus.abrir_pendiente_security` + `pendientes-security.json`): los
pendientes nuevos se comentan en ella con `company_requests.MARCA_PENDIENTE_SEC`, que `evidencia_nueva` deja pasar aunque la firme el supervisor.
Trampa: `respuesta_operador` salta el freno UNA vez y `lanzar_request` la limpia (hasta SC-1977 la rama del bot no lo hacía y un comentario
de Dani apagaba el freno para siempre: SC-1862, 99 encargos en 24 h). La política está también en la cabecera de `jira-epic-trigger.py`.
Una plaza ocupada sin progreso cede el sitio (SC-2249, `ceder_plazas` al final del barrido): con el cupo lleno (`ocupan` ≥ `tope`) y alguien esperando
(las Requests «sin hueco» y las épicas «sin hueco» o «esperando hueco»; no las que esperan al proveedor de su modelo, «(no se admite)»), el ocupante que
lleva `CEDER_HORAS` (3, una sola variable) ocupando plaza —`st["ocupa_desde"]`, desde cuándo el barrido lo ve ocupar sin soltar— y sin progreso se aparca
`CEDER_HORAS` con `aparcar_hasta` (`parked-hasta-<ISO>`). «Sin progreso» es `company_desatascador.SupervisorEfectos.ultimo_progreso` (ningún comentario ajeno
al supervisor, adjunto ni cambio de estado), la misma lectura que el desatascador. Soltar la plaza sin perder el trabajo: el encargo del bot recibe el aviso
(`aviso_aparcado_bot`, el mismo de la orden `aparcar` del vigilante) de cerrar su turno con la espera `fecha <hora>`
(`company-sesion cerrar … --espera`, `espera_aparcado`), la que vigila el despertador y con la que el encargo vuelve a despertarse al vencer el
aparcado: la etiqueta sola no lo despierta. Una sesión con unidad recibe el mismo aviso como lo pendiente (`ep["pendiente"]`, se le entrega al reanudarla) y se para: se reanuda con `--resume` sobre su sid y sabe por qué la pararon. Como mucho uno por cada uno que
espera, primero el que más tiempo lleva sin progreso; el ya aparcado que aún no soltó cuenta como cedido; nunca lo que Dani ejecuta en vivo, una Acción ni lo
que Jira no deja leer. La plaza la toma el primero de la cola en el siguiente barrido. Tras desplegar, ningún ocupante cede hasta `CEDER_HORAS` después
(`ocupa_desde` nace vacío).
Test: `ci/test_jira_epic_trigger.py::RequestsSinBucleSC1977` y `::SinNovedadSC1985` (reloj simulado, ledger real en un tmp), `::CederPlazaSC2249`, `ci/test_despertador.py::Esperas` (el aparcado de un bot vuelve a despertarse), `ci/test_company_huella.py`, `ci/test_company_encargos.py` y
`ci/test_company_bus_poda.py::PendienteSecurity`.

## Componente canónico: la señal de cierre del turno (SC-1987)

`company-sesion cerrar --estado resuelta|espera|pregunta|para-dani` (con `--espera` repetible y `--motivo`) escribe la
señal del turno en `DIR/senales/<perfil>--<key>.json` (`company_encargos.registrar_senal`; atómico, un fichero por
conversación, fuera de `encargos.json` porque `_leer/_guardar` no tienen cerrojo y el supervisor lo reescribe entero).
La leen `company_encargos._turno` (`senal_del_turno(perfil, key, t0)`: no se consume al leerla, caduca por `at < t0`),
`despertador.tras_turno(..., senal=)` (la sintetiza como líneas `ESPERA:` y usa la única gramática, `esperas_de`) y
`para_el_topic`. Solo `resuelta` cierra los encargos; `registrar_senal` no mueve ninguna Request ni toca `tratar_request`.
Sin señal se lee la prosa como antes (sesiones de Claude CLI, SOULs sin resembrar); si discrepan, para las esperas (`_turno`, despertador, espera externa)
manda la señal y se loguea; en el filtro del topic la señal solo manda con `pregunta` y `para-dani` (el texto sale tal
cual) y con `espera` o `resuelta` el filtro sigue leyendo el texto como siempre. `company_senal_total{via}` cuenta cada turno. Lista única de motivos: `company_encargos.MOTIVOS_DANI`.
SC-2075: el texto que `para_el_topic` saca a la persona lo acota `company_acotar.acotar` (480 caracteres y 4 líneas del mensaje entero —cabecera y enlace incluidos—, primera frase y últimas frases con «…» en medio; contrato `lenguaje.acotar.v1` y fixture `ci/fixtures/acotar_casos.json`, que copia el pod; una sola fuente que lee también `ci/lenguaje_check.py`; el AVISO DE ENTREGA y las opciones `N. texto` de una pregunta no se cortan; lo cortado lleva «El resto, en <KEY>.» y el enlace al Despacho, y deja una línea en `acotado.log`). Acota la salida, no el último mensaje dentro de la sesión del bot. Las secretarias y los perfiles fuera de la compañía no pasan por él.
Contrato: `cli.company-sesion.cerrar.senal` (`schema`) y `cli.company-sesion.cerrar.motivo` (`allowlist`).
SC-2058: lo que el despertador entrega a un bot de Hermes (EVENTO, esperas imposibles, aviso sin dueño) va en lenguaje natural y pide las esperas por esta señal (`company_briefs.pie_espera`, único sitio del comando); al tech-lead CLI y a las secretarias les llega el texto de siempre (`mensaje_evento` sin `perfil`).

[DECISION: la señal del turno es un campo y viaja en los argumentos de `cerrar`, en fichero propio y sin consumirse al
leer; el parser de texto se retira en otro ticket cuando `via=texto` sea ~0. Architect, SC-1987, 06-10-2026.]

## Componente canónico: el turno abierto de una sesión (SC-2064 P5a)

[DECISION: x86-host-runtime-pocharlies: el componente canónico de «este turno de la sesión ya está cerrado» es `company_capacidad.turno_cerrado_de(jet, s)` sobre `jira-epic-trigger.turno_cerrado(sid, desde)`; el sello `abierto` de la entrada del registro de company-sesion lo escribe solo `company-sesion` (lanzar, mensaje, relanzar_por_cuota). Architect, `nota-architect-plan.md` P5a-1 a P5a-6, 08-10-2026]

Cada entrada de `~/.company/sesiones/registro.json` lleva, además de `visto` y `turno_visto` (lo que el bus ya repartió), `abierto`
(epoch): el instante en que `company-sesion` le abrió el último turno. Se toma ANTES de pegar el texto o de lanzar la unidad y se
escribe solo si el mensaje llegó; `apuntar` fusiona con el máximo (el bus apunta entradas leídas antes). `jet.turno_cerrado(sid, desde)`
solo da por cerrado el turno cuyo evento de cierre y última línea del asistente son de `desde` o posteriores (el `timestamp` de la
línea; sin `ESTADO:` obligatorio: pm, it y security cierran sin él); sin `desde` o sin `timestamp` legible, vale la lógica de siempre.
`turno_cerrado_de(jet, s)` es la única lectura de `abierto` y la usan los seis sitios que miran el turno de una entrada:
`company_bus.turnos_cerrados` y `barrer_ociosas`, `company_capacidad.trabajando`, `company-sesion` (`mensaje`, `leer`, `ver`),
`company_encargos._sesion_trabajando` y `despertador.despertadores`. `esperar_turno` pasa su propio `desde` a `turno_cerrado`.
El sello caduca: a los `TURNO_GRACIA_S` (120 s) de `abierto` sin que el turno nuevo aparezca, el mensaje no llegó y vale el cierre
de siempre, así que una sesión nunca se queda «trabajando» por un mensaje perdido. Una entrada sin `abierto` (anterior a esto) se
comporta como antes, y un `company-sesion` viejo con u