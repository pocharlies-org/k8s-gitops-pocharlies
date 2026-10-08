# PR review: contexto extra (`scripts/review-context.py`)

INFRA-298 / INFRA-330. Genera `.review/context.md`, que lee PR-Agent junto al diff. Solo aporta hechos:
las reglas de contratos siguen en `scripts/check-contracts.py`.

Seis secciones fijas, en orden: Contratos tocados · Trailers Contract-Change · Consumidores del registry ·
PRs abiertas que solapan · Memoria local-ops · Degradaciones (líneas `Aviso · <fuente>: <motivo>`).

Registry de Synapse, solo lectura y offline (sin `/search/code`, que da 429):

    git clone --no-checkout --depth 1 https://github.com/pocharlies-org/synapse _synapse
    git -C _synapse sparse-checkout set libs/synapse-contracts && git -C _synapse checkout
    python scripts/review-context.py --base origin/main --head HEAD \
        --registry _synapse/libs/synapse-contracts/registry.yaml --out .review/context.md

Además de context.md escribe `contract-findings.json` junto a `--out`: los hallazgos de contrato
deterministas — `value` mutado in situ, sin trailer `Contract-Change` del id y sin bloque `exception` —
con fichero, línea del value en head, valores viejo/nuevo, consumidores y cuerpo del comentario. Es la
señal de entrada del inline publicado por `review-distribute.py` (seguimiento D del arquitecto): el
hallazgo no depende de que el modelo obedezca.

Entorno: `GH_TOKEN` (PRs abiertas), `BRAIN_URL`, `BRAIN_CI_KEY` (sin ella la memoria va a Degradaciones).
Salidas: 0 (también degradado), 2 uso inválido, 4 si una API responde 401/403. `--dry-run` no usa git ni red.
El HTTP (AuthError/Degraded/cliente) es común a los tres scripts del motor: `scripts/review_http.py`.
Tests: `python3 -m unittest tests/test_review_context.py`.

# PR review: configuración de PR-Agent y secretos por repo (INFRA-331)

**`.pr_agent.toml`** (raíz de este repo) es la configuración central de PR-Agent 0.46.0. El workflow
reusable (INFRA-332) la monta como configuración de host del contenedor:
`-v <checkout>/.pr_agent.toml:/app/pr_agent/settings_prod/.secrets.toml:ro`. Sin secretos ni endpoints:
`OPENAI_KEY` (secreto `PR_AGENT_LITELLM_KEY`), `OPENAI__API_BASE` (input `litellm_url`),
`JIRA__JIRA_API_EMAIL` y `JIRA__JIRA_API_TOKEN` (secretos `JIRA_EMAIL`, `JIRA_API_TOKEN`) llegan por entorno.

PR-Agent **no revienta** con un TOML roto: lo salta y sigue con sus valores por defecto (`gpt-5.6`,
`restricted_mode=false`, `auto_describe` encendido). Medido con la imagen fijada. Por eso:

    python3 scripts/check-pr-agent-config.py [--upstream <configuration.toml de v0.46.0>]

Falla (exit 1) si el TOML no parsea, si deriva una decisión (modelo D4, `auto_describe=false` D5,
`auto_review=true` y `auto_improve=true`, `restricted_mode`, `fallback_models`, `jira.project_keys`), si lleva
una credencial o un endpoint, o, con `--upstream`, si una clave no existe en esa versión. El CI lo corre
contra el fichero upstream fijado por commit y sha256. El workflow que monte el fichero debe correrlo antes
de lanzar PR-Agent.

`auto_improve` va encendido (decisión 5 del CTO): e improve no toca título ni cuerpo de la PR.
`auto_describe` sigue apagado hasta F3.

El inline del hallazgo de contrato NO pasa por PR-Agent: lo publica el CI por la API de GitHub
(`review-context.py` → `review-distribute.py`, marcador `<!--contrato:…-->`, anclado a la línea del
value en head, idempotente entre pushes). La clave `pr_reviewer.inline_key_issues` se retiró del
fichero y del REQUIRED del validador en INFRA-334: en 0.46.0 es inerte en GitHub (el provider no
implementa la verificación que exige `can_verify_inline_comment_publication`; solo bitbucket la
tiene). Por eso `suggestions_score_threshold` vale 1 (el default con
el que nació el fichero; #466 lo bajó a 0 y publicaba todas las sugerencias, también las flojas que
`self_reflect_on_suggestions` puntuaba 0 — ruido en todos los repos `engine: pr-agent`). El filtro de
calidad vuelve a valer; `artifact_instructions` pide ahora al modelo NO repetir el hallazgo como
sugerencia y dejarlo como primer key issue en la tabla de la review.

Equivalencias con los nombres del encargo: «output_language» es `config.response_language = "es-ES"`;
«enable_persistent_comments» es `persistent_comment = true` en `[pr_reviewer]` y `[pr_code_suggestions]`;
`require_ai_usage_from_owner/collaborator` no existe en 0.46.0.

**Secretos por repo** (plan `free`: un secreto de org no llega a los privados):

    scripts/review-distribute-secrets.sh --dry-run --repos k8s-litellm-pocharlies,skirmshop-labels
    scripts/review-distribute-secrets.sh --repos <r1,r2> [--from-vault pr-review-ci] [--rotate]

Reparte `PR_AGENT_LITELLM_KEY`, `JIRA_EMAIL` y `JIRA_API_TOKEN` (`BRAIN_CI_KEY` no, hasta que security
responda SC-1400). `--secrets A,B` elige el juego (los de PR-Agent de arriba o los del juez); el del juez (SC-2182) es
`--secrets LITELLM_JUEZ_KEY,JIRA_JUEZ_EMAIL,JIRA_JUEZ_TOKEN,JIRA_JUEZ_URL`, con nombres propios para no tocar ni rotar
`LITELLM_CI_KEY`, `JIRA_EMAIL` y `JIRA_API_TOKEN`. Valor: variable de entorno del mismo nombre o, con `--from-vault`, Vault KV v2
`secret/<ruta>` (necesita `VAULT_ADDR` y `VAULT_TOKEN`; el token va a curl por `-H @fichero` 0600, nunca en
su argv). Viaja por stdin a `gh secret set`; nunca se imprime.
Un secreto ya presente no se toca sin `--rotate`, así que reejecutar no cambia nada. Salida: una línea
`repo=… secreto=… estado=… accion=… fuente=…` por par y un `RESUMEN`. Códigos: 0 · 2 uso, repo
inexistente o valor ausente (sin escribir nada) · 4 401/403 · 1 otro fallo. El token de `gh` necesita
admin del repo. Tests: `python3 -m unittest tests/test_pr_agent_config.py`.

Key de LiteLLM: alias `pr-agent-ci`, solo `alibaba-q38-flash`, 6 rpm / 240 000 tpm (dos PR a la vez),
separada de `ci-review-bot` (equipo `ci-review`, 3 rpm / 120 000 tpm).

# PR review: el workflow reusable v2 y `inputs.engine` (INFRA-332)

`.github/workflows/reusable-pr-review.yml` tiene tres motores (el tercero, `juez`, en la sección siguiente). `engine: propio` (por defecto) es `review.py`,
sin cambios: lo siguen usando los 108 repos de la plantilla hasta INFRA-334. `engine: pr-agent` lo encienden
solo los pilotos, en su `.github/workflows/pr-review.yml`; la lista operativa de esos repos es
`.github/pr-agent-repos.txt` (única: la mide la señal nocturna y la siguen las oleadas de INFRA-334):

    uses: pocharlies-org/k8s-gitops-pocharlies/.github/workflows/reusable-pr-review.yml@main
    with:
      engine: pr-agent

Job `revisar_pr_agent`, en orden: pull de la imagen de Harbor por digest (en segundo plano) → contexto
(`review-context.py` → `.review/context.md`, más «Tickets Jira citados en el PR») → **validación del
fichero montado** (`check-pr-agent-config.py` dentro de la imagen fijada, contra su `configuration.toml`;
si falla, el motor no se lanza y el job queda verde con `status: skipped`) → PR-Agent (`docker run`, el
contexto le llega por `ARTIFACT_PATH` y las instrucciones de `[artifacts]` del `.toml`) → distribución
(`review-distribute.py` con el markdown de `push_outputs`, las etiquetas, el push-ingest y el inline
determinista de `contract-findings.json`) → artefacto `.review/` (14 días) → veredicto.

Permisos del job: `contents: read` + `pull-requests: write`. No `issues: write`: un job llamado que pide un
permiso que el llamador no concede tumba el run entero al arrancar, y la plantilla no lo concede;
`pull-requests: write` cubre comentarios y etiquetas del PR (tabla oficial de permisos de GitHub).

Rojo solo por 401/403 (LiteLLM, GitHub, Harbor, brain) o uso inválido (D3). Sin `PR_AGENT_LITELLM_KEY`, sin
`HARBOR_*`, modelo caído, timeout o config inválida: verde con aviso y `status` `skipped`/`degraded`.
El 401/403 de PR-Agent lo decide `scripts/pr-agent-auth-check.py` (INFRA-620): solo cuentan las líneas de log
ERROR/WARNING/CRITICAL, la excepción adjunta o un traceback crudo entero (hasta el siguiente registro de log; así cuenta un
`BadCredentialsException: 401` del token de GitHub); el volcado DEBUG/INFO del diff y del prompt no (un diff con
`status_code == 401` no es una credencial rota). El formato del log se midió con PR-Agent 0.46 (la del
`PR_AGENT_IMAGE`); si se sube la imagen hay que volver a medirlo.

Defensa contra la config: los valores críticos van también por entorno del contenedor
(`CONFIG__RESTRICTED_MODE`, `GITHUB_ACTION_CONFIG__AUTO_DESCRIBE`, `CONFIG__MODEL`, `CONFIG__FALLBACK_MODELS`,
`OPENAI__API_BASE`, `GITHUB__BASE_URL`, `JIRA__JIRA_SITE`). Medido con la imagen fijada: sin ellos, un
`.pr_agent.toml` en el tronco del repo revisado revierte todos esos valores, incluidos los destinos de las
credenciales; con ellos, ninguno (sí puede cambiar ajustes no críticos, p. ej. `ai_timeout`).

Imagen: `harbor.e-dani.com/homelab/pr-agent:0.46.0-github_action@sha256:42c7833a…` (espejo del manifiesto
linux/amd64). La vigila la entrada `pr-agent` de `dgx-infra ci/update-watch.yaml` (aviso, sin PR automático).

## Tiempo del job `pr-agent`: el pull y el camino crítico (INFRA-334)

El `docker pull` de la imagen arranca en el paso 2 del job y corre en segundo plano
(`Wait for the image pull` solo recoge el rc). Medido sobre los pilotos: **27 s de pull**
(p. ej. run 37003693367, `pull: rc=0 en 27 s`), que solapa con los checkouts. Pre-pull
«imagen ya en el runner» es **estructuralmente imposible** con este pool: en ARC v2
(`gha-runner-scale-set` 0.14.1) el pod del runner es efímero por job y el sidecar `dind`
lo inyecta el chart con args y volúmenes fijos (sin knob para `--registry-mirror` ni para
un volumen en `/var/lib/docker`); no hay store que perdurar entre jobs, y un pre-pull en
initContainer solo movería los 27 s a la cola, que el comando de medida del p95 también
cuenta (`run_started_at` → `updated_at`).

Lo que sí estaba en el camino crítico era el checkout del registry de Synapse: 25–41 s por
job. La causa **no** es el historial del fetch: sin `FRAMEWORK_REPO_TOKEN` en el repo
llamador, `actions/checkout` recibe **404** al resolver el ref de `pocharlies-org/synapse`
(repo privado) y **reintenta con backoff** («Waiting 19 seconds before trying again», medido
en los logs del run 37265193905). Fijar `ref:` no lo evita (el backoff está también en el
fetch de autenticación — medido en runs aislados: el paso seguía en 28–35 s). El fix es la
**puerta determinista** del paso (INFRA-334, delta del architect): sin
`FRAMEWORK_REPO_TOKEN` el paso no se ejecuta (`if: ... && env.FRAMEWORK_REPO_TOKEN != ''`,
con el secret mapeado a `env:` del job — el contexto `secrets` no está disponible en un `if:`
de paso); `review-context.py` anota la fuente en «Degradaciones» y sale 0, igual que con el
checkout fallido. `fetch-depth: 1` se mantiene (el registry se lee como fichero del HEAD).
El p95 del job sobre la muestra vieja era 101–112 s; la evidencia de los 10 runs con la
puerta va en el `50-entrega.md` de INFRA-334 (criterio del CTO, comentario 18462).
El comando de medida es el del spec de INFRA-332 criterio 4, sobre runs del piloto con diff
≤ 120 KB:

    gh api "repos/pocharlies-org/<piloto>/actions/workflows/<WF>/runs?per_page=100" \
      --jq '[.workflow_runs[] | ((.updated_at|fromdate) - (.run_started_at|fromdate))] | sort | .[((length*0.95)|floor)]'

## Puerta del pr-watcher: etiquetas y códigos 6 y 7 (INFRA-353 / INFRA-392)

El `pr-watcher` (`~/.claude/skills/pr-watcher`) es el consumidor de la etiqueta
`changes_required` que pone `review-distribute.py`: solo bloquea la etiqueta **vigente**
(check-run `<job del llamador> / Review del PR (PR-Agent)` con `head_sha` = HEAD y
`success`); sin run del HEAD actual la etiqueta es obsoleta y no hace nada. Salidas:
**6** = bloqueada por `changes_required` vigente (la review del HEAD pide cambios: no se
fusiona, no se reintentará el merge); **7** = check-runs caído con la etiqueta puesta
(la puerta no pudo comprobar la vigencia: reintento uno, y si vuelve a fallar no fusiona;
la PR queda para el siguiente ciclo y quien la relanza es el consumidor al despertar).
Nunca fusiona por defecto: `merge`/`needs_human`/`unknown` del artefacto no autorizan, solo
dejan aplicar las demás puertas.

## Dependencia externa: SC-1400

El ticket Jira y la memoria del brain van **degradados** hasta que SC-1400 dé la cuenta de
solo lectura (`JIRA_EMAIL`/`JIRA_API_TOKEN`) y `BRAIN_CI_KEY` por repo: sin ellas el
push-ingest sale `sin_clave` (la señal nocturna lo informa aparte, no cuenta como omitido)
y la sección «Tickets Jira citados» del contexto va a Degradaciones. El reparto de esas
claves y las oleadas de `engine: pr-agent` a los 108 repos son el resto de INFRA-334
(criterios 0–2 y 7), tras el visto bueno de security y el sign-off de INFRA-333.

## Señal de salud nocturna (`review-health.yml`, INFRA-333)

`.github/workflows/review-health.yml` (cron 03:17 UTC + `workflow_dispatch`, runner `arc-k8s`) corre
`scripts/review-health.py` sobre cada repo de `.github/pr-agent-repos.txt` (la única lista de los
`engine: pr-agent`; cada oleada de INFRA-334 añade su repo ahí, y `extra_repos` solo vale para un
dispatch puntual). Lee los runs de `PR review` de las últimas 24 h —la ventana la calcula el workflow
(`date -u -d '24 hours ago'`), no hay fecha fija en el YAML— hasta 50, y el artefacto
`pr-review-<pr>-<intento>` de cada uno (`payload.json` + `distribute.json`).

- **Omitido** = sin artefacto dentro de la retención (14 d), `status` ≠ `ok`, o push-ingest/etiquetas `degradado`
  (el brain o GitHub dieron 4xx/5xx) o `rechazado` (401/403). Cuenta una vez por run.
- **Rojo** (job en rojo + aviso al topic `ci`) si omitidos > 20 % de los runs medibles (10 de 50 es verde, 11 es rojo; con
  menos de 50 runs, sobre los que haya) o si el último run terminó en `failure` (credencial rota).
- **No cuentan**: runs sin el motor PR-Agent (`engine: propio`, forks), anteriores a `--since`, sin datos por retención, y
  `push_ingest: sin_clave` (falta `BRAIN_CI_KEY`, SC-1400): se informa aparte como dependencia.
- Si no se puede medir (GitHub caído) sale 3, no verde. Es la puerta de cada oleada de INFRA-334.

# PR review: el motor `juez` (SC-2182)

`engine: juez` no revisa el diff: **juzga** si el PR cumple los criterios de aceptación de su ticket de Jira. Es el
motor que sustituye a qa + architect en las historias de la compañía. Nace **opt-in** (`propio` sigue siendo el
default; el cambio de default es otra PR, solo con la lista medida de repos cubierta de secretos):

    uses: pocharlies-org/k8s-gitops-pocharlies/.github/workflows/reusable-pr-review.yml@main
    with:
      engine: juez

Job `Review del PR (juez)` (`revisar_pr_juez`), solo en `pull_request`; el check se llama `<job del llamador> / Review del
PR (juez)`. Un solo motor por evento (`tests/test_reusable_pr_review.py -k un_solo_motor`): `revisar_pr` y
`revisar_commit` corren solo con `engine: propio`, `revisar_pr_agent` con `pr-agent`; un motor que no existe pone
rojo el job `Motor de review no valido`. Con `engine: juez`, `workflow_dispatch` corre la evaluación (abajo).

**Qué lee.** Todo entra por entorno y como datos delimitados con una marca aleatoria por ejecución (el modelo no
obedece nada de lo que haya dentro): los criterios del ticket, el diff y el `ARCHITECTURE.md` **del commit base** (no el
del head: un PR no reescribe las reglas con las que se le juzga). La clave del ticket sale del título, si no de la rama,
si no del cuerpo (proyectos `SC INFRA DGX SKIRM LE OWU ACC`; la primera clave de la primera fuente que cite alguna). Los
criterios son las líneas `- [ ]` del adjunto `00-spec.md` más reciente de la historia o, si no hay, los elementos de la
sección «Criterios de aceptación» de su descripción. Jira, de solo lectura: secretos `JIRA_EMAIL` y `JIRA_API_TOKEN`.

**Qué decide.** El modelo aporta hechos y el código aplica la regla. Por criterio, el modelo dice `cumple` y la
evidencia, una línea `fichero:línea` de la versión NUEVA que el diff muestra; si falta o no está en el diff, ese criterio
no cuenta (`sin_evidencia`). Además cuenta todo hallazgo de severidad alta o media salvo los de tipo `estilo` u
`otro`: el tipo se normaliza (minúsculas, sin tildes) y un tipo desconocido o vacío (`bug`, `corrección` mal escrito)
bloquea, porque el motivo de no bloquear es el estilo, no una etiqueta que el modelo escribió distinta. Un `NO_PASA`
sin hallazgos del modelo (`sin_clave`, `ticket_inexistente`, `cita_epica`, `sin_criterios`) lleva su motivo como
línea `**[ticket]**` de `### Hallazgos`, para que el maker tenga algo que arreglar. Jira devuelve 404 también cuando
la cuenta de solo lectura no ve el ticket: sale como `ticket_inexistente`.

| veredicto | cuándo | job |
|---|---|---|
| `PASA` | todos los criterios cumplen con evidencia en el diff y ningún hallazgo bloquea | verde |
| `NO_PASA` | sin clave de ticket (`sin_clave`), ticket inexistente, ticket de tipo épica (`cita_epica`), sin criterios, criterio incumplido, sin evidencia o hallazgo bloqueante | rojo |
| `SIN_VEREDICTO` | sin credencial (LiteLLM o Jira), Jira o los dos modelos caídos, respuesta del modelo inservible | rojo |

`SIN_VEREDICTO` no es culpa de quien abrió el PR. El juez no conoce `SIN_TICKET`: esa exención es solo de
`company-aprobar` (x86), que en un PR exento ignora este check. Un diff recortado por `max_diff_bytes` fuerza
`riesgo=alto`; la regla determinista de riesgo por ruta vive en `company-aprobar`, no aquí.

**Fallback.** Cada llamada corta a 90 s como máximo; un timeout cuenta como un 408. Ante timeout, 408, 429, 5xx o
400/401/403/404 del modelo primario (`model`) se juzga con `fallback_model` (por defecto `alibaba-q38-flash`); otro 4xx
no cae al respaldo, y el respaldo no tiene respaldo. Con `model == fallback_model` no hay segundo intento. Con el
respaldo, la descripción del ticket, el `00-spec.md` y el `ARCHITECTURE.md` salen también al plan Team de Alibaba, no solo
el diff (revisión de `security` de SC-2181, punto v).

**El marcador v2** (contrato `ci.llm-review-bot.marcador.v2`, marcado en `review.py`). Un comentario por PR, que se
actualiza en cada head, escrito por `github-actions[bot]` (un comentario ajeno con la misma marca no se toca). Su
PRIMERA línea es exactamente

    <!-- llm-review-bot:v2 sha=<40 hex> veredicto=PASA|NO_PASA|SIN_VEREDICTO riesgo=normal|alto motivos=<enum> -->

con `motivos` un enum cerrado (`MOTIVOS` en `review.py`), nunca texto libre; lo que escribe el modelo o el ticket llega
al comentario en una línea y sin `<`, así que un marcador falso dentro de un hallazgo no cuenta. Bajo `### Hallazgos`
va una línea `- ` por cosa que arreglar (criterio incumplido, sin evidencia, hallazgo bloqueante): es lo que el maker
recibe. El lector (`company-aprobar`, x86) y este escritor comparten `tests/fixtures/juez/marcador-v2.json`, idéntico
byte a byte en los dos repos. Si el comentario no se puede publicar (llamador sin `pull-requests: write`) el job sale en
rojo: un veredicto que nadie puede leer no vale.

**Un PR desde un fork** no recibe secretos: el job sale en verde sin marcador, y `company-aprobar` sin marcador queda
en su modo legado.

**Evaluación** (`workflow_dispatch` con `engine: juez`, o a mano):

    REVIEW_LITELLM_URL=… REVIEW_LITELLM_KEY=… REVIEW_MODEL=… \
      python3 .github/actions/llm-review/review.py --evalua tests/fixtures/juez --umbral 7/8

Corre el juez con el modelo real sobre los 8 casos de `tests/fixtures/juez/` (4 PASA y 4 NO_PASA: criterio incumplido,
bug, norma de arquitectura, sin tests; los PASA son commits reales de este repo y los NO_PASA, diffs reales estropeados a propósito: sin el test, con una condición
invertida, con una interpolación en un `run`) y sale 0 solo si acierta al menos 7 de 8. Un `SIN_VEREDICTO` cuenta como fallo. Tests sin red:
`python3 -m unittest tests.test_llm_review_juez` (un LiteLLM, un Jira y una API de GitHub de pega).

## Cobertura: qué repos pasan a `juez` y con qué (SC-2182, parte C)

Cambiar el `engine` por defecto del reusable a `juez` afecta a todo repo que lo llama sin fijar `engine:`. Dos listas
medidas (el 2026-10-08, leyendo el árbol de workflows de cada repo, no por búsqueda de código: esa no indexa los
privados) dicen a quién:

- `.github/pr-review-llamadores.txt`: TODOS los repos que llaman a `reusable-pr-review.yml` (176 entre `pocharlies-org`
  y la cuenta `pocharlies`) con su estado, el `engine` que fijan, a qué versión apuntan y su **cobertura**: `secretos`
  (los cuatro del juez como secretos del repo), `propio` (el repo fija `engine: propio`), `pr-agent`, `archivado` (sin
  PR posible) o `pendiente`.
- `.github/pr-review-juez-repos.txt`: los repos donde la compañía abre PRs (`tracker.projects` de `company-options.json`),
  con si llaman ya al reusable. Esos nunca fijan `engine: propio`: quedan en `juez`. `skirmshop-picqer` está fuera a
  propósito (cuenta personal, `runner: ubuntu-latest`: no alcanza el LiteLLM del cluster).

**Los cuatro secretos del juez** (SC-2182): `LITELLM_JUEZ_KEY` (key `ci-review-juez`), `JIRA_JUEZ_EMAIL`, `JIRA_JUEZ_TOKEN`
y `JIRA_JUEZ_URL` (cuenta de servicio de Jira de solo lectura). Sus valores están en 1Password (`k8s-pocharlies`:
`litellm-ci-review-juez` y `jira-juez-pr-review`) y se reparten por repo a todos los llamadores activos salvo los tres de
la cuenta personal, que fijan `engine: propio`.

Un repo con la cobertura `pendiente` vería un `SIN_VEREDICTO` rojo con el default en `juez`. El test
`python3 -m unittest tests.test_reusable_pr_review -k cobertura` falla si el default es `juez` y queda alguno. Comprobación
viva, sin escribir nada ni imprimir valores (`estado=ausente` es lo que hay que borrar de la salida):

    scripts/review-distribute-secrets.sh --dry-run --secrets LITELLM_JUEZ_KEY,JIRA_JUEZ_EMAIL,JIRA_JUEZ_TOKEN,JIRA_JUEZ_URL --repos <unión de las dos listas>

Un secreto de organización no vale como cobertura: el plan de la org es `free` y no llega a los repos privados ni a los de
la cuenta personal, así que el reparto es por repo.
