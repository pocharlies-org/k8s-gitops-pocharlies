# SC-2264: evidencia de la rama SC-2264-calibracion

Donde: x86 (`ubuntu`), worktree de `k8s-gitops-pocharlies`, sobre 1ece33d (origin/main) + esta rama. Sin modelo real: el residente
`tooling` estaba caído y la medida con el respaldo no vale (C6).

| comando | resultado |
|---|---|
| `python3 -m unittest discover -s tests -p 'test_*.py'` | PASS, 404 tests, 1 skipped |
| `python3 -m unittest tests.test_llm_review_juez` | PASS, 214 tests (hermético, modelo de pega) |
| `python3 -m unittest tests.test_reusable_pr_review` | PASS, 33 tests (el nuevo C7 falla contra el workflow de main) |
| `python3 scripts/check-workflow-pins.py` | All third-party workflow dependencies are pinned to immutable commits |
| `company-duplicados` | Sin duplicación nueva |

Split (`scripts/juez_split.py`, 52 casos): entrenamiento 11, validación 25, prueba 16.

| criterio | dónde |
|---|---|
| C1 | `tests.test_llm_review_juez` (corpus ≥ 50, una clase y un esperado por caso, `TestSplit`) |
| C2 | `TestEsquema`; la comprobación con el residente queda para la medida (la línea final de `--evalua` dice qué alias aceptó el esquema) |
| C3 | `TestFases` (2 + ceil(criterios/5) llamadas por PR) |
| C4 | `test_un_hallazgo_de_correccion_sin_el_caso_concreto_baja_a_observacion_por_codigo`, `TestSplit.test_ningun_ejemplo_de_la_rubrica_sale_de_validacion_ni_de_prueba` |
| C7 | `tests.test_reusable_pr_review.test_la_evaluacion_mide_la_parte_de_prueba_con_pasadas_y_umbrales_del_split` |
| C8 | el marcador v3 y su fixture `tests/fixtures/juez/marcador-v3.json` no se tocan |
| C5, C6 | pendientes de la medida con el modelo real (ramas `medida/SC-2264` y `medida/SC-2264-antes`) |
