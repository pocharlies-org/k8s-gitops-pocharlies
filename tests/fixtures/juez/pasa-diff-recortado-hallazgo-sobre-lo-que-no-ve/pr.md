SC-9003: tabla de veredictos del juez

## Que cambia

- `scripts/pr-review-report.py`: lee el JSON de PRs de la entrada estandar y llama a `render(filas)` de `review_report_lib`.
- `scripts/review_report_lib.py`: `render` con celdas escapadas y columnas alineadas, y los formateadores por veredicto.
- `tests/test_pr_review_report.py`, en `ci.yml`: una PR y ninguna.

## Verificacion

`python3 -m unittest tests/test_pr_review_report.py`: 2 OK.
