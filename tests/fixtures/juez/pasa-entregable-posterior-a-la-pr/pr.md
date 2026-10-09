SC-9002: scripts/redact-keys.py oculta las keys de LiteLLM en los logs

## Que cambia

- `scripts/redact-keys.py`: `ocultar(texto)` cambia por `***` toda `sk-` seguida de 16 o mas caracteres alfanumericos.
- `tests/test_redact_keys.py`, en `ci.yml`: dos keys en una linea y una cadena demasiado corta.

## Despues del merge

Lo mide qa en el job real: su `70-qa.md`, la captura del resumen del job y el comentario del ticket con la fecha de produccion se adjuntan al ticket tras el despliegue. No forman parte de esta PR.

## Verificacion

`python3 -m unittest tests/test_redact_keys.py`: 2 OK.
