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
Tests: `python -m pytest tests/test_review_context.py -q`.
