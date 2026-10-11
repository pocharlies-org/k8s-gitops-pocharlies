# SC-2264: evidencia de la rama iter/SC-2264-c (iteración 3, variante C)

Donde: x86 (`ubuntu`), worktree de `k8s-gitops-pocharlies`, sobre df5a7d6 (SC-2264-calibracion). Sin modelo real: la medida la hace el
workflow `medida/SC-2264-c` con el proxy `alibaba-q38-flash`.

| comando | resultado |
|---|---|
| `python3 -m unittest discover -s tests -p 'test_*.py'` | PASS, 414 tests, 1 skipped |
| `python3 -m unittest tests.test_llm_review_juez` | PASS, 224 tests (hermético, modelo de pega) |
| `python3 scripts/check-workflow-pins.py` | All third-party workflow dependencies are pinned to immutable commits |
| `company-duplicados` | Sin duplicación nueva |

Variante C = el diseño por fases de df5a7d6 con tres arreglos:
1. el juicio de cada lote recibe también el diff de los ficheros que nombran sus criterios (`diff_de_los_nombrados`, tope `LOTE_DIFF_MAX`);
2. un criterio sin citas es ➖ «no demostrable en el diff», salvo la ausencia de un fichero que no está en el diff ni en el head;
3. los hallazgos de la caza de fallos nunca bloquean (observaciones), estén atados o no.

Tests nuevos: `TestVarianteC` (16, rojos antes del cambio en el commit anterior). Los que afirmaban que un hallazgo bloquea se
reescribieron (el verificador se prueba ahora con un ❌ por contradicción) o se borraron (reglas de cita de un hallazgo).
Código que queda sin camino vivo (los hallazgos ya no bloquean): `aplicar_reglas` y `citas_sin_casar` sobre hallazgos, `a_verificar`
de hallazgos y el motivo `hallazgos` de `decidir`; si C gana, se borran en la PR final.
