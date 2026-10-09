# SC-2229: medida local del juez por mayoría de tiradas

Dónde: el x86 (`ubuntu`), worktree de la rama `sc-2229-juez-mayoria`, 09-10-2026, por la mañana. Con `REVIEW_LITELLM_URL=https://litellm.lan.e-dani.com`, `REVIEW_MODEL=tooling`, `REVIEW_FALLBACK_MODEL=alibaba-q38-flash`, `REVIEW_TIMEOUT_SECONDS=90`. La key `ci-review-juez` salió de 1Password a una variable de entorno y no se imprimió.

Comando (un contador envuelve `pedir` para sumar llamadas y tokens; `gasto_usd` es la diferencia de `spend` de la key en `/key/info` antes y después):

    REVIEW_TIRADAS=<1|3> python3 .github/actions/llm-review/review.py --evalua <dir> --umbral <N/M>

`<dir>` es `tests/fixtures/juez` (corpus, 9 casos) o los 20 casos reales de SC-2197 montados por qa (formato de `tests/fixtures/juez`, `esperado` = veredicto de qa, 70-qa.md). Los 20 reales vienen de repos privados y este repo es público, así que no están en el árbol (ver la PR).

## Resultado

Veredicto: **FALLA el criterio 5**. Con 3 tiradas el juez acierta entre 10 y 13 de los 20 reales (objetivo: 16) y entre 8 y 9 de los 9 del corpus (objetivo: 8). Falsos PASA por mayoría: 0 en M1 y M2, 1 en M3 (dgx-infra#1104). Una tirada suelta dio PASA a #1104 en M1.

| serie | tiradas | reales (aciertos por mayoría) | peor resultado | falsos PASA (mayoría / alguna tirada) | corpus (mayoría / peor) |
|---|---|---|---|---|---|
| línea base, réplica 1 | 1 | 9/20 | 9/20 | 1 / 1 | 9/9 |
| línea base, réplica 2 | 1 | 11/20 | 11/20 | 0 / 0 | |
| **M1 (lo que entrega la PR)** | 3 | **12/20** | 6/20 | 0 / 1 | **8/9** / 6/9 |
| M2 (variante retirada) | 3 | 13/20 | 8/20 | 0 / 0 | 9/9 / 6/9 |
| M3 (repetición de M2) | 3 | 10/20 | 5/20 | 1 / 1 | |

La línea base es el mismo código con `REVIEW_TIRADAS=1`. M2 y M3 añadían al prompt una regla «un criterio de otra parte de la historia o un entregable posterior es fuera»: no mejoró de forma medible (13 y 10 de 20, el mismo ruido que entre réplicas) y puede empujar a dejar pasar lo que falta, así que se retiró; la PR entrega M1. Entre réplicas del mismo código hay 3 aciertos de diferencia, así que ninguna de las diferencias de la tabla es firme con 20 casos.

Siete casos fallan en al menos dos de las tres series de 3 tiradas (x86#801, #802, #803, #804, k8s-ai#123, opencode#252 y x86#798). La mayoría no los arregla porque el error se repite en las tres tiradas: el juez da ❌ a criterios de otra parte de la historia, da por rotas cosas en diffs de 100 KB o más que qa no dio por rotas, o cita como evidencia una línea que no está en el diff recortado. Son hipótesis sobre las notas de las tiradas; no las verifiqué una a una.

## Coste por PR (criterio 4)

| serie | llamadas | por PR | tokens entrada | USD (delta de la key) | USD por PR |
|---|---|---|---|---|---|
| M1 reales (20 PRs) | 71 (9 al respaldo) | 3,55 | 1,69 M | 0,0358 | 0,0018 |
| M1 corpus (9 casos) | 34 (4 al respaldo) | 3,78 | 0,27 M | 0,0209 | 0,0023 |
| línea base reales | 20 y 24 | 1,0 y 1,2 | 0,54 M y 0,61 M | 0,0106 y 0,0132 | 0,0005 y 0,0007 |

Con 3 tiradas cada PR gasta de 3 a 4 llamadas (el respaldo y el reintento cuentan, la tercera tirada se ahorra cuando dos ya deciden) y unos 0,002 USD. El `max_budget` de `ci-review-juez` es 2 USD/día: unos 1.000 PRs al día. El `spend` de la key estaba en 0,055 USD al empezar la mañana y en 0,109 al terminar, con todas estas series y otras sesiones que usan la misma key. El `gasto_usd` de una serie es la diferencia de `spend` y suma a quien llame a la vez, así que es una cota alta.

Latencia: en M1, 2.430 s de llamadas para 71 llamadas (34 s de media con el `tooling` compartido con otras mediciones; 9 llamadas cayeron al respaldo por timeout de 90 s). En M1 las 20 PRs tardaron 2.520 s en total (unos 2 min por PR, con el `tooling` compartido).

## Criterios del `00-spec.md`

- C1 juez por N tiradas, constante 3, PASA solo con mayoría limpia y sin ❌ con línea citada, marcador v2 igual: cumplido (`TestMayoria`, `TestMarcadorFixture`).
- C2 `--evalua` con N tiradas, peor resultado y mayoría: cumplido (`TestEvaluaTiradas`).
- C3 el corpus gana los casos reales de SC-2197: NO cumplido en el árbol, a propósito (repo público, diffs de repos privados). Medidos fuera del repo, los 20.
- C4 coste por PR contra el `max_budget`: cumplido (tabla de arriba).
- C5 0 falsos PASA y ≥ 16/20: NO cumplido (arriba).

Pruebas del repo (CI de este repo, cada fichero con `python3 -m unittest`): `tests/test_llm_review_juez.py` 77 OK; `tests/test_reusable_pr_review.py`, `test_review_*`, `test_duplicados`, `test_release_*`, `test_synapse_sre_foundation_app` OK; `scripts/check-*.py` y `scripts/test-*.py` OK; `company-duplicados`: sin duplicación nueva.

## Salida de cada serie (solo las líneas por caso, sin avisos)

### Linea base: 1 tirada (REVIEW_TIRADAS=1), 20 reales, replica 1 (mitades a y b)

```
FALLO dgx-infra-1104: esperado=NO_PASA obtenido=PASA motivos=- tiradas=PASA peor=FALLO
OK    dgx-infra-1105: esperado=PASA obtenido=PASA motivos=- tiradas=PASA peor=OK
OK    dgx-infra-1106: esperado=PASA obtenido=PASA motivos=- tiradas=PASA peor=OK
FALLO dgx-infra-1107: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA peor=FALLO
FALLO k8s-ai-pocharlies-123: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido tiradas=NO_PASA peor=FALLO
FALLO k8s-ai-pocharlies-125: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido tiradas=NO_PASA peor=FALLO
OK    k8s-ai-pocharlies-126: esperado=NO_PASA obtenido=NO_PASA motivos=criterio_incumplido tiradas=NO_PASA peor=OK
OK    k8s-gitops-pocharlies-552: esperado=PASA obtenido=PASA motivos=- tiradas=PASA peor=OK
FALLO k8s-openclaw-qwen36-pocharlies-579: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido tiradas=NO_PASA peor=FALLO
OK    k8s-openclaw-qwen36-pocharlies-580: esperado=PASA obtenido=PASA motivos=- tiradas=PASA peor=OK
aciertos 5/10 (umbral 5/10)
peor resultado 5/10 · falsos PASA 1 (en alguna tirada: 1)
{"llamadas": 10, "por_modelo": {"tooling": 10}, "tokens_in": 268654, "tokens_out": 6825, "segundos": 125, "no_ok": 0, "segundos_total": 216, "gasto_usd": 0.00549}
FALLO opencode-company-252: esperado=PASA obtenido=NO_PASA motivos=hallazgos tiradas=NO_PASA peor=FALLO
FALLO x86-host-runtime-pocharlies-798: esperado=PASA obtenido=NO_PASA motivos=hallazgos tiradas=NO_PASA peor=FALLO
FALLO x86-host-runtime-pocharlies-801: esperado=PASA obtenido=NO_PASA motivos=hallazgos tiradas=NO_PASA peor=FALLO
FALLO x86-host-runtime-pocharlies-802: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido tiradas=NO_PASA peor=FALLO
OK    x86-host-runtime-pocharlies-803: esperado=PASA obtenido=PASA motivos=- tiradas=PASA peor=OK
FALLO x86-host-runtime-pocharlies-804: esperado=PASA obtenido=NO_PASA motivos=hallazgos tiradas=NO_PASA peor=FALLO
OK    x86-host-runtime-pocharlies-805: esperado=PASA obtenido=PASA motivos=- tiradas=PASA peor=OK
FALLO x86-host-runtime-pocharlies-806: esperado=PASA obtenido=NO_PASA motivos=sin_evidencia tiradas=NO_PASA peor=FALLO
OK    x86-host-runtime-pocharlies-807: esperado=PASA obtenido=PASA motivos=- tiradas=PASA peor=OK
OK    x86-host-runtime-pocharlies-808: esperado=PASA obtenido=PASA motivos=- tiradas=PASA peor=OK
aciertos 4/10 (umbral 5/10)
peor resultado 4/10 · falsos PASA 0 (en alguna tirada: 0)
{"llamadas": 10, "por_modelo": {"tooling": 10}, "tokens_in": 275699, "tokens_out": 4414, "segundos": 256, "no_ok": 0, "segundos_total": 346, "gasto_usd": 0.00511}
```

### Linea base: 1 tirada, 20 reales, replica 2

```
OK    dgx-infra-1104: esperado=NO_PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA peor=OK
FALLO dgx-infra-1105: esperado=PASA obtenido=NO_PASA motivos=hallazgos tiradas=NO_PASA peor=FALLO
FALLO dgx-infra-1106: esperado=PASA obtenido=NO_PASA motivos=hallazgos tiradas=NO_PASA peor=FALLO
OK    dgx-infra-1107: esperado=PASA obtenido=PASA motivos=- tiradas=PASA peor=OK
FALLO k8s-ai-pocharlies-123: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos,sin_evidencia tiradas=NO_PASA peor=FALLO
FALLO k8s-ai-pocharlies-125: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA peor=FALLO
OK    k8s-ai-pocharlies-126: esperado=NO_PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos,sin_evidencia tiradas=NO_PASA peor=OK
OK    k8s-gitops-pocharlies-552: esperado=PASA obtenido=PASA motivos=- tiradas=PASA peor=OK
FALLO k8s-openclaw-qwen36-pocharlies-579: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA peor=FALLO
OK    k8s-openclaw-qwen36-pocharlies-580: esperado=PASA obtenido=PASA motivos=- tiradas=PASA peor=OK
aciertos 5/10 (umbral 5/10)
peor resultado 5/10 · falsos PASA 0 (en alguna tirada: 0)
{"llamadas": 11, "por_modelo": {"tooling": 11}, "tokens_in": 313276, "tokens_out": 12910, "segundos": 240, "no_ok": 0, "segundos_total": 331, "gasto_usd": 0.00618}
FALLO opencode-company-252: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA peor=FALLO
FALLO x86-host-runtime-pocharlies-798: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido tiradas=NO_PASA peor=FALLO
FALLO x86-host-runtime-pocharlies-801: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA peor=FALLO
OK    x86-host-runtime-pocharlies-802: esperado=PASA obtenido=PASA motivos=- tiradas=PASA peor=OK
FALLO x86-host-runtime-pocharlies-803: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA peor=FALLO
OK    x86-host-runtime-pocharlies-804: esperado=PASA obtenido=PASA motivos=- tiradas=PASA peor=OK
OK    x86-host-runtime-pocharlies-805: esperado=PASA obtenido=PASA motivos=- tiradas=PASA peor=OK
OK    x86-host-runtime-pocharlies-806: esperado=PASA obtenido=PASA motivos=- tiradas=PASA peor=OK
OK    x86-host-runtime-pocharlies-807: esperado=PASA obtenido=PASA motivos=- tiradas=PASA peor=OK
OK    x86-host-runtime-pocharlies-808: esperado=PASA obtenido=PASA motivos=- tiradas=PASA peor=OK
aciertos 6/10 (umbral 5/10)
peor resultado 6/10 · falsos PASA 0 (en alguna tirada: 0)
{"llamadas": 13, "por_modelo": {"tooling": 11, "alibaba-q38-flash": 2}, "tokens_in": 301339, "tokens_out": 8600, "segundos": 464, "no_ok": 2, "segundos_total": 555, "gasto_usd": 0.00698}
```

### Linea base: 1 tirada, corpus de 9

```
OK    no-pasa-bug-condicion-invertida: esperado=NO_PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA peor=OK
OK    no-pasa-criterio-sin-cumplir: esperado=NO_PASA obtenido=NO_PASA motivos=criterio_incumplido tiradas=NO_PASA peor=OK
OK    no-pasa-norma-de-arquitectura: esperado=NO_PASA obtenido=NO_PASA motivos=hallazgos tiradas=NO_PASA peor=OK
OK    no-pasa-sin-tests: esperado=NO_PASA obtenido=NO_PASA motivos=criterio_incumplido tiradas=NO_PASA peor=OK
OK    pasa-deteccion-de-credencial-rota: esperado=PASA obtenido=PASA motivos=- tiradas=PASA peor=OK
OK    pasa-invariantes-del-payload: esperado=PASA obtenido=PASA motivos=- tiradas=PASA peor=OK
OK    pasa-pr-de-pin-gitops: esperado=PASA obtenido=PASA motivos=- tiradas=PASA peor=OK
OK    pasa-sin-key-en-rojo: esperado=PASA obtenido=PASA motivos=- tiradas=PASA peor=OK
OK    pasa-skipdirs-contracts-checker: esperado=PASA obtenido=PASA motivos=- tiradas=PASA peor=OK
aciertos 9/9 (umbral 8/9)
peor resultado 9/9 · falsos PASA 0 (en alguna tirada: 0)
{"llamadas": 10, "por_modelo": {"tooling": 10}, "tokens_in": 86992, "tokens_out": 3506, "segundos": 107, "no_ok": 0, "segundos_total": 197, "gasto_usd": 0.00141}
```

### M1 (lo que se entrega): 3 tiradas, prompt de main + la linea citada en un rojo, 20 reales

```
OK    dgx-infra-1104: esperado=NO_PASA obtenido=NO_PASA motivos=hallazgos tiradas=PASA,NO_PASA,NO_PASA peor=FALLO
OK    dgx-infra-1105: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,NO_PASA peor=FALLO
OK    dgx-infra-1106: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,NO_PASA peor=FALLO
OK    dgx-infra-1107: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,NO_PASA peor=FALLO
FALLO k8s-ai-pocharlies-123: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos,sin_evidencia tiradas=NO_PASA,NO_PASA,NO_PASA peor=FALLO
OK    k8s-ai-pocharlies-125: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,PASA peor=OK
OK    k8s-ai-pocharlies-126: esperado=NO_PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA,NO_PASA,NO_PASA peor=OK
OK    k8s-gitops-pocharlies-552: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,PASA peor=OK
OK    k8s-openclaw-qwen36-pocharlies-579: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,NO_PASA,PASA peor=FALLO
OK    k8s-openclaw-qwen36-pocharlies-580: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,PASA peor=OK
FALLO opencode-company-252: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA,NO_PASA,PASA peor=FALLO
FALLO x86-host-runtime-pocharlies-798: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA,NO_PASA,NO_PASA peor=FALLO
FALLO x86-host-runtime-pocharlies-801: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido tiradas=PASA,NO_PASA,NO_PASA peor=FALLO
FALLO x86-host-runtime-pocharlies-802: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA,NO_PASA,NO_PASA peor=FALLO
FALLO x86-host-runtime-pocharlies-803: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido tiradas=NO_PASA,NO_PASA,NO_PASA peor=FALLO
FALLO x86-host-runtime-pocharlies-804: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA,NO_PASA,PASA peor=FALLO
OK    x86-host-runtime-pocharlies-805: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,PASA peor=OK
OK    x86-host-runtime-pocharlies-806: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,NO_PASA,PASA peor=FALLO
OK    x86-host-runtime-pocharlies-807: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,PASA peor=OK
FALLO x86-host-runtime-pocharlies-808: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA,PASA,NO_PASA peor=FALLO
aciertos 12/20 (umbral 16/20)
peor resultado 6/20 · falsos PASA 0 (en alguna tirada: 1)
{"llamadas": 71, "por_modelo": {"tooling": 62, "alibaba-q38-flash": 9}, "tokens_in": 1691155, "tokens_out": 42611, "segundos": 2430, "no_ok": 9, "segundos_total": 2520, "gasto_usd": 0.03577}
```

### M1: 3 tiradas, corpus de 9

```
OK    no-pasa-bug-condicion-invertida: esperado=NO_PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA,NO_PASA,NO_PASA peor=OK
OK    no-pasa-criterio-sin-cumplir: esperado=NO_PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA,NO_PASA,NO_PASA peor=OK
OK    no-pasa-norma-de-arquitectura: esperado=NO_PASA obtenido=NO_PASA motivos=hallazgos tiradas=NO_PASA,NO_PASA,NO_PASA peor=OK
OK    no-pasa-sin-tests: esperado=NO_PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA,NO_PASA,NO_PASA peor=OK
FALLO pasa-deteccion-de-credencial-rota: esperado=PASA obtenido=NO_PASA motivos=hallazgos tiradas=NO_PASA,PASA,NO_PASA peor=FALLO
OK    pasa-invariantes-del-payload: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,NO_PASA peor=FALLO
OK    pasa-pr-de-pin-gitops: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,PASA peor=OK
OK    pasa-sin-key-en-rojo: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,NO_PASA,PASA peor=FALLO
OK    pasa-skipdirs-contracts-checker: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,PASA peor=OK
aciertos 8/9 (umbral 8/9)
peor resultado 6/9 · falsos PASA 0 (en alguna tirada: 0)
{"llamadas": 34, "por_modelo": {"tooling": 30, "alibaba-q38-flash": 4}, "tokens_in": 267192, "tokens_out": 21349, "segundos": 1248, "no_ok": 4, "segundos_total": 1339, "gasto_usd": 0.0209}
```

### M2 (variante probada y retirada): M1 + regla «lo de otra parte es fuera», 20 reales (mitades a y b)

```
OK    dgx-infra-1104: esperado=NO_PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA,NO_PASA,NO_PASA peor=OK
OK    dgx-infra-1105: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,PASA peor=OK
OK    dgx-infra-1106: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,NO_PASA peor=FALLO
OK    dgx-infra-1107: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,NO_PASA,PASA peor=FALLO
FALLO k8s-ai-pocharlies-123: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos,sin_evidencia tiradas=NO_PASA,NO_PASA,NO_PASA peor=FALLO
OK    k8s-ai-pocharlies-125: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,NO_PASA,PASA peor=FALLO
OK    k8s-ai-pocharlies-126: esperado=NO_PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA,NO_PASA,NO_PASA peor=OK
OK    k8s-gitops-pocharlies-552: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,PASA peor=OK
FALLO k8s-openclaw-qwen36-pocharlies-579: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido tiradas=NO_PASA,NO_PASA,PASA peor=FALLO
OK    k8s-openclaw-qwen36-pocharlies-580: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,PASA peor=OK
aciertos 8/10 (umbral 8/10)
peor resultado 5/10 · falsos PASA 0 (en alguna tirada: 0)
{"llamadas": 36, "por_modelo": {"tooling": 30, "alibaba-q38-flash": 6}, "tokens_in": 811212, "tokens_out": 22305, "segundos": 1462, "no_ok": 6, "segundos_total": 1552, "gasto_usd": 0.01578}
FALLO opencode-company-252: esperado=PASA obtenido=NO_PASA motivos=hallazgos tiradas=PASA,NO_PASA,NO_PASA peor=FALLO
OK    x86-host-runtime-pocharlies-798: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,NO_PASA peor=FALLO
FALLO x86-host-runtime-pocharlies-801: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=PASA,NO_PASA,NO_PASA peor=FALLO
FALLO x86-host-runtime-pocharlies-802: esperado=PASA obtenido=NO_PASA motivos=sin_evidencia tiradas=PASA,NO_PASA,NO_PASA peor=FALLO
FALLO x86-host-runtime-pocharlies-803: esperado=PASA obtenido=NO_PASA motivos=hallazgos,sin_evidencia tiradas=NO_PASA,NO_PASA,NO_PASA peor=FALLO
FALLO x86-host-runtime-pocharlies-804: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA,NO_PASA,NO_PASA peor=FALLO
OK    x86-host-runtime-pocharlies-805: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,NO_PASA,PASA peor=FALLO
OK    x86-host-runtime-pocharlies-806: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,PASA peor=OK
OK    x86-host-runtime-pocharlies-807: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,PASA peor=OK
OK    x86-host-runtime-pocharlies-808: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,PASA peor=OK
aciertos 5/10 (umbral 8/10)
peor resultado 3/10 · falsos PASA 0 (en alguna tirada: 0)
{"llamadas": 31, "por_modelo": {"tooling": 31}, "tokens_in": 858557, "tokens_out": 14952, "segundos": 847, "no_ok": 0, "segundos_total": 937, "gasto_usd": 0.01083}
```

### M2 (variante retirada): corpus de 9 (mitades c1 y c2)

```
OK    no-pasa-bug-condicion-invertida: esperado=NO_PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA,NO_PASA,NO_PASA peor=OK
OK    no-pasa-criterio-sin-cumplir: esperado=NO_PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA,NO_PASA,NO_PASA peor=OK
OK    no-pasa-norma-de-arquitectura: esperado=NO_PASA obtenido=NO_PASA motivos=hallazgos tiradas=NO_PASA,NO_PASA,NO_PASA peor=OK
OK    no-pasa-sin-tests: esperado=NO_PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA,NO_PASA,NO_PASA peor=OK
OK    pasa-deteccion-de-credencial-rota: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,NO_PASA peor=FALLO
aciertos 5/5 (umbral 4/5)
peor resultado 4/5 · falsos PASA 0 (en alguna tirada: 0)
{"llamadas": 16, "por_modelo": {"tooling": 15, "alibaba-q38-flash": 1}, "tokens_in": 130758, "tokens_out": 6555, "segundos": 488, "no_ok": 1, "segundos_total": 578, "gasto_usd": 0.00774}
OK    pasa-invariantes-del-payload: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,NO_PASA peor=FALLO
OK    pasa-pr-de-pin-gitops: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,PASA peor=OK
OK    pasa-sin-key-en-rojo: esperado=PASA obtenido=PASA motivos=- tiradas=NO_PASA,PASA,PASA peor=FALLO
OK    pasa-skipdirs-contracts-checker: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,PASA peor=OK
aciertos 4/4 (umbral 3/4)
peor resultado 2/4 · falsos PASA 0 (en alguna tirada: 0)
{"llamadas": 12, "por_modelo": {"tooling": 12}, "tokens_in": 113835, "tokens_out": 5043, "segundos": 255, "no_ok": 0, "segundos_total": 346, "gasto_usd": 0.00309}
```

### M3 (variante retirada, repeticion de M2): 20 reales en cinco trozos de 4

```
FALLO dgx-infra-1104: esperado=NO_PASA obtenido=PASA motivos=- tiradas=PASA,NO_PASA,PASA peor=FALLO
OK    dgx-infra-1105: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,NO_PASA,PASA peor=FALLO
FALLO dgx-infra-1106: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA,NO_PASA,NO_PASA peor=FALLO
OK    dgx-infra-1107: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,PASA peor=OK
aciertos 2/4 (umbral 3/4)
peor resultado 1/4 · falsos PASA 1 (en alguna tirada: 1)
{"llamadas": 14, "por_modelo": {"tooling": 13, "alibaba-q38-flash": 1}, "tokens_in": 432845, "tokens_out": 7106, "segundos": 336, "no_ok": 1, "segundos_total": 426, "gasto_usd": 0.00477}
FALLO k8s-ai-pocharlies-123: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos,sin_evidencia tiradas=NO_PASA,NO_PASA,NO_PASA peor=FALLO
OK    k8s-ai-pocharlies-125: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,NO_PASA peor=FALLO
OK    k8s-ai-pocharlies-126: esperado=NO_PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA,NO_PASA,NO_PASA peor=OK
OK    k8s-gitops-pocharlies-552: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,PASA peor=OK
aciertos 3/4 (umbral 3/4)
peor resultado 2/4 · falsos PASA 0 (en alguna tirada: 0)
{"llamadas": 17, "por_modelo": {"tooling": 12, "alibaba-q38-flash": 5}, "tokens_in": 252360, "tokens_out": 12607, "segundos": 798, "no_ok": 5, "segundos_total": 888, "gasto_usd": 0.00437}
FALLO k8s-openclaw-qwen36-pocharlies-579: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=PASA,NO_PASA,NO_PASA peor=FALLO
OK    k8s-openclaw-qwen36-pocharlies-580: esperado=PASA obtenido=PASA motivos=- tiradas=NO_PASA,PASA,PASA peor=FALLO
OK    opencode-company-252: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,PASA peor=OK
FALLO x86-host-runtime-pocharlies-798: esperado=PASA obtenido=NO_PASA motivos=hallazgos tiradas=NO_PASA,NO_PASA,PASA peor=FALLO
aciertos 2/4 (umbral 3/4)
peor resultado 1/4 · falsos PASA 0 (en alguna tirada: 0)
{"llamadas": 14, "por_modelo": {"tooling": 14}, "tokens_in": 330565, "tokens_out": 8913, "segundos": 460, "no_ok": 0, "segundos_total": 550, "gasto_usd": 0.00274}
FALLO x86-host-runtime-pocharlies-801: esperado=PASA obtenido=NO_PASA motivos=hallazgos tiradas=NO_PASA,NO_PASA,NO_PASA peor=FALLO
FALLO x86-host-runtime-pocharlies-802: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA,NO_PASA,PASA peor=FALLO
FALLO x86-host-runtime-pocharlies-803: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA,NO_PASA,NO_PASA peor=FALLO
FALLO x86-host-runtime-pocharlies-804: esperado=PASA obtenido=NO_PASA motivos=criterio_incumplido,hallazgos tiradas=NO_PASA,PASA,NO_PASA peor=FALLO
aciertos 0/4 (umbral 3/4)
peor resultado 0/4 · falsos PASA 0 (en alguna tirada: 0)
{"llamadas": 14, "por_modelo": {"tooling": 14}, "tokens_in": 534345, "tokens_out": 11708, "segundos": 293, "no_ok": 0, "segundos_total": 383, "gasto_usd": 0.0038}
OK    x86-host-runtime-pocharlies-805: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,PASA peor=OK
OK    x86-host-runtime-pocharlies-806: esperado=PASA obtenido=PASA motivos=- tiradas=PASA,PASA,NO_PASA peor=FALLO
OK    x86-host-runtime-pocharlies-807: esperado=PASA obtenido=PASA motivos=- tiradas=NO_PASA,PASA,PASA peor=FALLO
FALLO x86-host-runtime-pocharlies-808: esperado=PASA obtenido=NO_PASA motivos=sin_evidencia tiradas=NO_PASA,NO_PASA,PASA peor=FALLO
aciertos 3/4 (umbral 3/4)
peor resultado 1/4 · falsos PASA 0 (en alguna tirada: 0)
{"llamadas": 15, "por_modelo": {"tooling": 13, "alibaba-q38-flash": 2}, "tokens_in": 267282, "tokens_out": 4858, "segundos": 445, "no_ok": 2, "segundos_total": 535, "gasto_usd": 0.0016}
```

