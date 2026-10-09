SC-9006: lista de PRs sin actividad (scripts/stale-prs.py)

## Que cambia

- `scripts/stale-prs.py`: `viejas(prs, ahora, dias)` devuelve las PRs cuyo `updatedAt` es anterior a `ahora - dias`.
- `tests/test_stale_prs.py`, en `ci.yml`: el limite exacto, una PR sin `updatedAt` y una lista vacia.

El script lo llamara un workflow en otra historia; esta PR solo trae la funcion y su test.

## Verificacion

`python3 -m unittest tests/test_stale_prs.py`: 3 OK.
