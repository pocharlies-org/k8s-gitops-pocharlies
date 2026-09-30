Rol: developer · Fecha: 2026-09-30T13:07:58Z · Sesión: 015nkGRb26CrG9xjgarGmHfx · Estado: LISTO

# INFRA-330 — entrega
Añade `scripts/review-context.py` (stdlib + PyYAML opcional), tests y fixtures pinned, y `docs/ci-pr-review.md`. Sin tocar el workflow reusable.

- [x] 1. Fixtures: 5 casos (value cambiado, .v2 añadido, exception, sin contratos, marca CONTRACT) → `python3 -m unittest tests/test_review_context.py` = 13 OK.
- [x] 2. Registry real (checkout sparse de synapse) sobre «value cambiado»: consumers ≥1 e id presentes.
- [x] 3. `git sparse-checkout list` → `libs/synapse-contracts` (comandos en docs/ci-pr-review.md).
- [x] 4. Sin BRAIN_CI_KEY / brain caído → exit 0 y línea «Aviso · brain»; con brain OK (servidor de prueba, clave `documents`) → `- [<fuente>] <resumen>`. Contra el brain real: pendiente de qa en arc-k8s (B1 abierta).
- [x] 5. `exception:` solo en lectura/reporte; sin lógica de aprobar/denegar. Nota: no importa el parser de check-contracts.py (C1) porque solo lee entradas YAML; extraerlo a módulo compartido queda a criterio del arquitecto.
- [x] 6. La clave no aparece en stdout/stderr/context (test).
- [x] 7. Doc: docs/ci-pr-review.md (nuevo).

Cómo verificar: unittest arriba; `python scripts/review-context.py --dry-run --repo x/y --pr 1` → 6 cabeceras.
Salidas: 0/2/4 cubiertas por tests (403 → 4 con solo sección 6). Sin cambios a contratos (.company/changes no aplica).
Tests cableados en ci.yml con unittest (la política de pins prohíbe pip install).
