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

Entorno: `GH_TOKEN` (PRs abiertas), `BRAIN_URL`, `BRAIN_CI_KEY` (sin ella la memoria va a Degradaciones).
Salidas: 0 (también degradado), 2 uso inválido, 4 si una API responde 401/403. `--dry-run` no usa git ni red.
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

`auto_improve` va encendido (decisión 5 del CTO): con 0.46.0 los hallazgos en la línea de código solo salen
por `/improve` (`/review` no publica inline), e improve no toca título ni cuerpo de la PR. `auto_describe`
sigue apagado hasta F3.

Equivalencias con los nombres del encargo: «output_language» es `config.response_language = "es-ES"`;
«enable_persistent_comments» es `persistent_comment = true` en `[pr_reviewer]` y `[pr_code_suggestions]`;
`require_ai_usage_from_owner/collaborator` no existe en 0.46.0.

**Secretos por repo** (plan `free`: un secreto de org no llega a los privados):

    scripts/review-distribute-secrets.sh --dry-run --repos k8s-litellm-pocharlies,skirmshop-labels
    scripts/review-distribute-secrets.sh --repos <r1,r2> [--from-vault pr-review-ci] [--rotate]

Reparte `PR_AGENT_LITELLM_KEY`, `JIRA_EMAIL` y `JIRA_API_TOKEN` (`BRAIN_CI_KEY` no, hasta que security
responda SC-1400). Valor: variable de entorno del mismo nombre o, con `--from-vault`, Vault KV v2
`secret/<ruta>` (necesita `VAULT_ADDR` y `VAULT_TOKEN`; el token va a curl por `-H @fichero` 0600, nunca en
su argv). Viaja por stdin a `gh secret set`; nunca se imprime.
Un secreto ya presente no se toca sin `--rotate`, así que reejecutar no cambia nada. Salida: una línea
`repo=… secreto=… estado=… accion=… fuente=…` por par y un `RESUMEN`. Códigos: 0 · 2 uso, repo
inexistente o valor ausente (sin escribir nada) · 4 401/403 · 1 otro fallo. El token de `gh` necesita
admin del repo. Tests: `python3 -m unittest tests/test_pr_agent_config.py`.

Key de LiteLLM: alias `pr-agent-ci`, solo `alibaba-q38-flash`, 6 rpm / 240 000 tpm (dos PR a la vez),
separada de `ci-review-bot` (equipo `ci-review`, 3 rpm / 120 000 tpm).

# PR review: el workflow reusable v2 y `inputs.engine` (INFRA-332)

`.github/workflows/reusable-pr-review.yml` tiene dos motores. `engine: propio` (por defecto) es `review.py`,
sin cambios: lo siguen usando los 108 repos de la plantilla hasta INFRA-334. `engine: pr-agent` lo encienden
solo los pilotos (`k8s-litellm-pocharlies`, `skirmshop-labels`), en su `.github/workflows/pr-review.yml`:

    uses: pocharlies-org/k8s-gitops-pocharlies/.github/workflows/reusable-pr-review.yml@main
    with:
      engine: pr-agent

Job `revisar_pr_agent`, en orden: pull de la imagen de Harbor por digest (en segundo plano) → contexto
(`review-context.py` → `.review/context.md`, más «Tickets Jira citados en el PR») → **validación del
fichero montado** (`check-pr-agent-config.py` dentro de la imagen fijada, contra su `configuration.toml`;
si falla, el motor no se lanza y el job queda verde con `status: skipped`) → PR-Agent (`docker run`, el
contexto le llega por `ARTIFACT_PATH` y las instrucciones de `[artifacts]` del `.toml`) → distribución
(`review-distribute.py` con el markdown de `push_outputs`) → artefacto `.review/` (14 días) → veredicto.

Permisos del job: `contents: read` + `pull-requests: write`. No `issues: write`: un job llamado que pide un
permiso que el llamador no concede tumba el run entero al arrancar, y la plantilla no lo concede;
`pull-requests: write` cubre comentarios y etiquetas del PR (tabla oficial de permisos de GitHub).

Rojo solo por 401/403 (LiteLLM, GitHub, Harbor, brain) o uso inválido (D3). Sin `PR_AGENT_LITELLM_KEY`, sin
`HARBOR_*`, modelo caído, timeout o config inválida: verde con aviso y `status` `skipped`/`degraded`.

Defensa contra la config: los valores críticos van también por entorno del contenedor
(`CONFIG__RESTRICTED_MODE`, `GITHUB_ACTION_CONFIG__AUTO_DESCRIBE`, `CONFIG__MODEL`, `CONFIG__FALLBACK_MODELS`,
`OPENAI__API_BASE`, `GITHUB__BASE_URL`, `JIRA__JIRA_SITE`). Medido con la imagen fijada: sin ellos, un
`.pr_agent.toml` en el tronco del repo revisado revierte todos esos valores, incluidos los destinos de las
credenciales; con ellos, ninguno (sí puede cambiar ajustes no críticos, p. ej. `ai_timeout`).

Imagen: `harbor.e-dani.com/homelab/pr-agent:0.46.0-github_action@sha256:42c7833a…` (espejo del manifiesto
linux/amd64). La vigila la entrada `pr-agent` de `dgx-infra ci/update-watch.yaml` (aviso, sin PR automático).

## Señal de salud nocturna (`review-health.yml`, INFRA-333)

`.github/workflows/review-health.yml` (cron 03:17 UTC + `workflow_dispatch`, runner `arc-k8s`) corre
`scripts/review-health.py` sobre cada repo con `engine: pr-agent` (hoy `k8s-litellm-pocharlies` y `skirmshop-labels`;
cada oleada de INFRA-334 añade los suyos a la lista del job `repos`, o se pasan en `extra_repos`). Lee los últimos 50 runs de
`PR review` y el artefacto `pr-review-<pr>-<intento>` de cada uno (`payload.json` + `distribute.json`).

- **Omitido** = sin artefacto dentro de la retención (14 d), `status` ≠ `ok`, o push-ingest/etiquetas `degradado`
  (el brain o GitHub dieron 4xx/5xx) o `rechazado` (401/403). Cuenta una vez por run.
- **Rojo** (job en rojo + aviso al topic `ci`) si omitidos > 20 % de los runs medibles (10 de 50 es verde, 11 es rojo; con
  menos de 50 runs, sobre los que haya) o si el último run terminó en `failure` (credencial rota).
- **No cuentan**: runs sin el motor PR-Agent (`engine: propio`, forks), anteriores a `--since`, sin datos por retención, y
  `push_ingest: sin_clave` (falta `BRAIN_CI_KEY`, SC-1400): se informa aparte como dependencia.
- Si no se puede medir (GitHub caído) sale 3, no verde. Es la puerta de cada oleada de INFRA-334.
