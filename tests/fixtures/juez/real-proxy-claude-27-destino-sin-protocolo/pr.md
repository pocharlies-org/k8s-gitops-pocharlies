SC-2161 P3: desvío de cuenta de las sesiones en vivo sin cuota y «sin créditos»

## Alcance de esta PR
- C5: las sesiones en vivo que se quedan sin cuota siguen en otra cuenta del orden sin intervención (desvío del router), y no gastan créditos de uso

**Orden de fusión:** primero pocharlies-org/claude-local-router#29 (la copia del plugin) y después esta. Hasta entonces `bundle-drift` va en rojo aquí. **Security revisa antes del merge** (plan §2.6 y §8; lo lanza la sesión).

## Qué hace

Cuando una sesión en vivo recibe un 429 de límite de suscripción, el router repite la misma petición con el setup-token de otra cuenta. Modelo, cuerpo y cabeceras van iguales: solo cambia `authorization`, que es la lección del desvío retirado el 17-09.

- «Sin cuota» es un 429 con `anthropic-ratelimit-unified-status: rejected` y reclamo `five_hour` o `seven_day`. La regla sale de una **captura real** (`tests/fixtures/429-limite-7d.json`, cuenta agotada de verdad, sin gastar nada) y mira solo cabeceras, porque Anthropic manda el cuerpo en br. Un 429 sin esa señal pasa intacto, y también está capturado (`429-sin-senal.json`).
- El orden lo escribe `company-agent` en `cuenta-failover.json` (`file.claude-failover.v1`, P2). El router solo lo lee, y solo actúa con `vivo: true` y un `generado` de menos de 10 minutos.
- Prueba hasta 2 candidatos, nunca la cuenta de origen ni otra de su organización, y con caché negativa. La primera que contesta 2xx se emite en streaming y queda como desvío pegajoso por cuenta de origen hasta su reset. Si ninguna sirve, sale el 429 original byte a byte (`FAILOVER-SIN-CUENTA`). Una cuenta que ha dicho `rejected` no se vuelve a probar hasta su reset.
- Quedan fuera, como hoy: la compañía (`x-claude-class: company`), `x-api-key`, los modelos locales y las peticiones forzadas a local.
- Tokens: solo los `<id>.token` de las cuentas que nombra el fichero (id de la regex del contrato, una línea, 0600, del mismo uid, `O_NOFOLLOW`). Ningún `.credentials.json`. Solo viajan a `https://api.anthropic.com` exacto (punto 1 de arriba); los logs y `/-/health` dicen el id o `h:` + 8 hex.
- `/-/health` gana `failover: {activo, sin_creditos, desvios, intentos, exitos, sin_cuenta, creditos}`, aditivo (`.company/changes/sc-2161-p3-desvio.md`).

**Sin créditos** (alcance que pidió Dani el 10-10). Una cuenta con créditos de uso activos no da 429 al agotarse: Anthropic la sirve con créditos y la sesión sigue gastando. Con `CLAUDE_ROUTER_SIN_CREDITOS=1` (en la unidad; no depende de `vivo`), un 2xx con esa señal no llega al cliente. El router corta la respuesta, prueba otra cuenta si el desvío está encendido y, si no hay ninguna, devuelve un 429 de límite (`FAILOVER-SIN-CUENTA-CREDITOS`). Hasta el reset, las peticiones siguientes de esa cuenta reciben el 429 sin salir a Anthropic. Las cabeceras están confirmadas en el binario de claude 2.1.296: `isUsingOverage` = `unified-status: rejected` y `unified-overage-status` en `allowed` o `allowed_warning`, y `overageInUse` = `unified-overage-in-use: true`. También lo probé con el CLI real: muestra «You've hit your limit» y deja `error: rate_limit` en el transcript, que es lo que lee el wrapper de SC-2267. Cada 2xx con créditos deja una línea `CREDITOS src=… headers={…}`. La fixture `200-creditos.json` es **sintética** (ninguna cuenta con créditos se ha agotado todavía) y lo dice en su `_nota`.

## Lo que no se ve en el diff

Ronda 2: arreglos por clase, no solo en la línea señalada. Líneas de `bin/claude-router.js` (en el plugin, `plugins/local-router/bin/claude-router.js`: son los mismos bytes).

1. **Destino exacto de los tokens (antes `:456`).** `UPSTREAM_OK` (línea 456) compara el `href` normalizado de `CLAUDE_ROUTER_ANTHROPIC_URL` con `https://api.anthropic.com/`, así que exige protocolo, host y puerto. El fake de los smokes solo vale con `http:`, `127.0.0.1` **y** `CLAUDE_ROUTER_FAILOVER_FAKE_UPSTREAM=1`, una variable que no aparece en la unidad, ni en el drop-in, ni en `install.sh` (`tests/smoke-install.js` lo comprueba). `SIN_CREDITOS` (458) también depende de `UPSTREAM_OK`, así que con otro destino el desvío y el 429 sintético quedan apagados, como hoy. Smokes: loopback sin la variable, `https://127.0.0.1`, `http://localhost` y `https://api.anthropic.com:8443` dan `activo: false` y `sin_creditos: false`.
2. **Logs escritos después de decidir (antes `:663`).** El `CREDITOS` de `forward` (690) va ahora detrás de `tomada()` y solo cuando la respuesta se sirve de verdad (`resultado=servida con creditos`). En las rutas del desvío, `logCreditos` (676) se llama con lo que pasó: `desviada a X`, `429 sintetico`, o `cortada en el candidato X; siguiente`. El resto de líneas `FAILOVER*` siguen la misma regla (`: servida`, `: se deja el desvio`, `el 429 original/sintetico`). Smoke: cada resultado sale una vez y «servida con creditos» solo aparece donde se sirvió.
3. **Fichero de orden que falla (antes `:508`).** `failoverCfg` (498): si el `stat` falla (fichero ausente o borrado en caliente), descarta la configuración y los tokens y **no intenta leer**. `leerOrden` (515): si la lectura falla después de un `stat` bueno (carrera con un borrado, fichero ilegible), lo mismo, y `mtime = null` hace que se reintente en el siguiente `stat`. Nunca se usa una configuración de más de 10 minutos (`generado`). Además, ninguna excepción del desvío sube y tumba el proceso: `tomada()` (686) protege los `intercept` de `forward`, `probarCandidatos` (632) va en `try` y emite el 429 que guardaba, y `sendAnthropic` (línea 801) cae a `forward`, como hoy. Smoke: se borra el fichero con el router vivo, la siguiente petición va como hoy (sin desvío ni pegajoso) y el desvío vuelve al reescribirlo.
4. **Una sola regla de corte por créditos (security, `:548` y `:576`).** `cortaPorCreditos(req, ur)` (478) la usan el original, el desvío pegajoso y los candidatos, y excluye `count_tokens`. Smoke: un `count_tokens` por la ruta pegajosa con créditos no se corta.

Funciones que el diff usa y ya existían: `log` (línea **119**), `fail` (354), `isCompany` (213), `scanLocalArtifacts` (313), `logLimit429` y `safe` (419 y 418, de P1), `ANTHROPIC` (87), `agents` (133) y `FORCE_HEADER` (170). `forward` (690) ya existía; el diff solo le añade el `intercept` opcional.

Copia del plugin, byte a byte:

```
$ sha256sum proxy-claude/bin/claude-router.js claude-local-router/plugins/local-router/bin/claude-router.js
2ae4739df7f586b84fa4af6b22162438f2643782dd13d7472eb1c581e24f0b44  proxy-claude/bin/claude-router.js
2ae4739df7f586b84fa4af6b22162438f2643782dd13d7472eb1c581e24f0b44  claude-local-router/plugins/local-router/bin/claude-router.js
```

El cambio se escribe y se prueba primero en proxy-claude#27, y luego se copia a claude-local-router#29 (la misma comprobación que `bundle-drift`). La evidencia, con la salida de los smokes (`smoke-failover` 53/53, `smoke-install` 13/13), las capturas reales y la medición de §2.4, está en `.company/evidence/sc-2161-p3-desvio.md` de proxy-claude. Los contratos `file.claude-failover.v1` y `file.claude-cuentas.v1` están registrados en el `CONTRACTS.yaml` de `pocharlies-org/x86-host-runtime-pocharlies`. Security aprobó los heads `8b95d06` y `567f04c` (`nota-security-p3.md` en SC-2161); esta ronda solo cierra los hallazgos de arriba.

## Riesgo §2.4: medido

Con cuentas reales, usando un router de esta rama en un puerto propio y un fichero de orden propio:
- Una sesión con `thinking` firmado por `sergio` (CloudBlue), retomada con `flash` agotada, pasó a `correo` (Moreno Ibáñez): **200**.
- Reenvié el turno de herramienta en curso, con la firma en el último `assistant`: **200**. Con `metadata.user_id` de la cuenta E-dani: **200**. La salida de §2.4 no hace falta.
- Coste del cambio: el primer turno en el destino tuvo `cache_read` 0 y `cache_creation` 25.153; el segundo, `cache_read` 25.153.

No hay un 429 de 5 h real: ninguna cuenta lo tenía sin tener también la semanal agotada. La regla acepta `five_hour` por ser el mismo campo, pero eso no está medido.

## Evidencia

`.company/evidence/sc-2161-p3-desvio.md`. `tests/smoke-failover.js` da **53/53**: los 7 smokes del plan, los de créditos y los de la ronda 2. `tests/smoke-install.js` da 13/13, y los otros cinco smokes siguen en verde. `.github/workflows/smokes.yml` los corre en `arc-k8s` en cada PR.

## Las variables van en un drop-in

`CLAUDE_ROUTER_FAILOVER_FILE`, `CLAUDE_ROUTER_ACCOUNTS_DIR` y `CLAUDE_ROUTER_SIN_CREDITOS=1` están en `systemd/claude-router.service.d/failover.conf`, no en la unidad. `install.sh` lo instala con 0644 en `~/.config/systemd/user/claude-router.service.d/`. El motivo es el `SessionStart` del plugin (`plugins/local-router/scripts/deploy.sh`): reescribe `claude-router.service` desde cero cada vez que despliega otros bytes. Con las variables en la unidad, el desvío y el corte de créditos se habrían apagado sin avisar en el siguiente despliegue del plugin. `deploy.sh` no toca `.service.d/`, igual que no toca los drop-ins hechos a mano. `tests/smoke-install.js` (13/13) lo demuestra con un HOME temporal y `systemctl` simulado: instala, ejecuta encima el `deploy.sh --force` del plugin público y el drop-in sigue intacto.

## Despliegue (devops, fuera de esta PR)

`./install.sh` reinicia `claude-router` y corta los streams de **todas** las sesiones, así que va en un hueco. El desvío sigue apagado hasta que alguien encienda `vivo` en el panel; «sin créditos» actúa desde el arranque.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

