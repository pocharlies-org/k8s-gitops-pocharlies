# SC-2277 · criterios del 00-spec.md

- [ ] El estado inicial de «nunca volcado» no depende del uptime del host (por ejemplo, None o -inf como centinela), en el código y en el test.
- [ ] Hay un test que fija monotonic() pequeño (uptime < AGG_FLUSH_MIN_S) y comprueba que el primer volcado escribe.
- [ ] El CI de main vuelve a verde y el despliegue del runtime sale.
