SC-9001: recuento de veredictos del juez (1/2: el script y su test)

## Que cambia

Primera de dos PRs de SC-9001. Añade `scripts/pr-review-stats.py` con `contar(comentarios)` y su test `tests/test_pr_review_stats.py`, que entra en `ci.yml`.

La segunda PR cablea el script en `reusable-pr-review.yml` y lo documenta en `docs/ci-pr-review.md`.

## Alcance de esta PR

- C1
- C2: el comentario sin marcador no cuenta, con su test

## Verificacion

`python3 -m unittest tests/test_pr_review_stats.py`: 2 OK.
