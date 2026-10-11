# SC-2264: evidencia de la rama iter/SC-2264-b (iteración 3, variante B)

Donde: x86 (`ubuntu`), worktree de `k8s-gitops-pocharlies`, sobre df5a7d6 (SC-2264-calibracion). Sin modelo real: la medida la hace el
workflow `medida/SC-2264-b` con el proxy `alibaba-q38-flash`.

| comando | resultado |
|---|---|
| `python3 -m unittest discover -s tests -p 'test_*.py'` | PASS, 399 tests, 1 skipped |
| `python3 -m unittest tests.test_llm_review_juez` | PASS, 209 tests (hermético, modelo de pega); rojos antes del cambio (commit anterior) |
| `python3 scripts/check-workflow-pins.py` | All third-party workflow dependencies are pinned to immutable commits |
| `company-duplicados` | Sin duplicación nueva |

Variante B: el juicio vuelve a la llamada única de main (criterios y hallazgos sobre el diff, el reintento de la cita que no casa y
las verificaciones de lo que bloquea); sin pasada de citas ni pregunta de caza de fallos. Conserva de df5a7d6 lo que no añade llamadas:
ejemplos de entrenamiento en la rúbrica, la regla de no afirmar de memoria, `json_schema` con respaldo, `--evalua` con detalle por
caso y el split. Las reglas deterministas de SC-2285 no se tocan.

Diferencia con main (1ece33d) en `review.py`: 176 líneas cambiadas, todas de lo conservado.
