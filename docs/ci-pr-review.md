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

Falla (exit 1) si el TOML no parsea, si deriva una decisión (modelo D4, `auto_describe`/`auto_improve` D5,
`restricted_mode`, `fallback_models`, `jira.project_keys`), si lleva una credencial o un endpoint, o, con
`--upstream`, si una clave no existe en esa versión. El CI lo corre contra el fichero upstream fijado por
commit y sha256. El workflow que monte el fichero debe correrlo antes de lanzar PR-Agent.

Equivalencias con los nombres del encargo: «output_language» es `config.response_language = "es-ES"`;
«enable_persistent_comments» es `persistent_comment = true` en `[pr_reviewer]` y `[pr_code_suggestions]`;
`require_ai_usage_from_owner/collaborator` no existe en 0.46.0.

**Secretos por repo** (plan `free`: un secreto de org no llega a los privados):

    scripts/review-distribute-secrets.sh --dry-run --repos k8s-litellm-pocharlies,skirmshop-labels
    scripts/review-distribute-secrets.sh --repos <r1,r2> [--from-vault pr-review-ci] [--rotate]

Reparte `PR_AGENT_LITELLM_KEY`, `JIRA_EMAIL` y `JIRA_API_TOKEN` (`BRAIN_CI_KEY` no, hasta que security
responda SC-1400). Valor: variable de entorno del mismo nombre o, con `--from-vault`, Vault KV v2
`secret/<ruta>` (necesita `VAULT_ADDR` y `VAULT_TOKEN`). Viaja por stdin a `gh secret set`; nunca se imprime.
Un secreto ya presente no se toca sin `--rotate`, así que reejecutar no cambia nada. Salida: una línea
`repo=… secreto=… estado=… accion=… fuente=…` por par y un `RESUMEN`. Códigos: 0 · 2 uso, repo
inexistente o valor ausente (sin escribir nada) · 4 401/403 · 1 otro fallo. El token de `gh` necesita
admin del repo. Tests: `python3 -m unittest tests/test_pr_agent_config.py`.

Key de LiteLLM: alias `pr-agent-ci`, solo `alibaba-q38-flash`, 6 rpm / 240 000 tpm (dos PR a la vez),
separada de `ci-review-bot` (equipo `ci-review`, 3 rpm / 120 000 tpm).
