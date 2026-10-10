DGX-780: conversor TP=3 de qwen38-flash-next (v4: PLE en el NVMe, divisor 384, rangos y forma PLE en verify, build_ple_table con TP=3)

Jira: DGX-780

Conversor TP=3 del híbrido qwen38-flash-next (7b719225) en `k8s/qwen38fn-tp3/convert.py`, con los modos convert, verify, plan, serve y publish y su test sin GPU. También cambia `build_ple_table.py`, que ahora acepta `TP_SIZE=3` (C15). La PR no toca ningún Deployment, así que el residente no se reinicia.

## Cambios en v4
- La tabla PLE ya no se reescribe. Ahora la sirve el NVMe de cada nodo (DGX-773), así que sus partes van como enlaces a la vista hermana. Se quitan la lógica de primos y la reescritura de la parte 127.
- `padded_vocab_size` se calcula como ceil(filas del checkpoint / 384) · 384, sumando las filas desde las cabeceras. `make_ngram_vocab_size_divisible_by` sube a 384 solo en el `config.json` de la vista TP=3 (C-1).
- `verify` ya no tiene la ventana PLE de `verify-loaders` ni carga `ngram_embedding` como pesos. Tiene dos comprobaciones nuevas:
  - (c) los rangos PLE de la imagen, sacados de `_make_vocab_layout` y `VocabParallelEmbedding._get_indices` sin instanciar la tabla (C-2), comparados con `build_ple_table.plan`;
  - (d) el chequeo de forma de `ngram_embedding.py:908-921`, con el `load_weights` de la imagen sobre las cabeceras de la vista.
- `build_ple_table.py` acepta `TP_SIZE=3`. Con `TP_SIZE=2` saca los mismos bytes que `63dd55f`.

La PR-A de DGX-780 está partida en cuatro PR contra `pin/qwen38-tp3-20261010`, porque el juez solo lee 120 KB:
- esta, #138;
- #139, los parches C5-C9, con C7b (`QWEN_TP3_PLE_SHARD_SKIP`);
- #140, los logits C11-C12;
- #141, los Jobs y `ci.yml`.

## Alcance de esta PR
- C1: comprueba el config.json de origen y escribe la vista TP=3 (KV 2→6, GDN 16:48→24:72 con reparto 6/5/5, shared 640→768, vocab 248448 con el tokenizador intacto, escalas FP8 con su bloque); la PLE no se reescribe, padded = ceil(filas/384)·384 y el divisor 384 solo en el config.json de la vista
- C2: solo la parte del conversor: enlaces relativos a la vista hermana en `publish` (también las partes PLE), GiB reescritos en el log y en `tp3-plan.json`, y el shard con expertos reescrito entero (N2). La comparación del SHA256SUMS antes y después la hace el Job, en #141
- C3: `tools/test_qwen38fn_tp3_convert.py`, sumas parciales de TP=2 frente a TP=3 en CPU (la PLE con la tabla que deja `build_ple_table.py`) y relleno a 0 exacto
- C4: `convert.py verify` → `verify.json` con (a) equivalencia, (b) `verify-loaders` con tp=3 en los rangos 0-2, (c) rangos PLE contra `build_ple_table.plan` y (d) forma de las partes PLE con el loader de la imagen; `"pasa"` solo si pasan las cuatro
- C15: `build_ple_table.py` acepta `TP_SIZE=3` (padded al divisor del config.json, rangos de `VocabParallelEmbedding`, relleno a cero) y con `TP_SIZE=2` da la misma salida byte a byte que `63dd55f`

## Cómo verificarlo
- `python -m unittest tools/test_qwen38fn_tp3_convert.py tools/test_qwen38_flashinfer_contract.py`: 13 y 28 tests, sin GPU ni torch.
- En `.company/evidence/DGX-780-tp3-checkpoint.md` están las cifras reales de la PLE, (c) y (d) en la imagen 96b234af, la comparación byte a byte con `63dd55f` y el render que muestra que head y worker no cambian.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

