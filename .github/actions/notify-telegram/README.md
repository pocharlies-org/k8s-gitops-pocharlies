# notify-telegram — quién la usa y qué se aprendió cableándola

Acción compartida para publicar avisos en el grupo de Telegram
**github pocharlies-org** (`-1003975290449`).

## Quién la llama

| llamante | topic | estados |
|---|---|---|
| `reusable-ci`, `reusable-release`, `reusable-deploy-stg`, `reusable-manifest-release`, `reusable-manifest-pr-release` | **`ci` = 69** | `audit_fail`, `rollback` |
| `release-bot-pocharlies/audit-fork.yml` | uno por fork (openchamber 3, shield 7, loki 9…) | los 9 |
| openclaw | `openclaw` = 47 | 6 avisos |

Los 5 reusables los consumen **37 repos** (24 públicos, 13 privados). No hace
falta tocar ninguno: heredan el cambio.

## Cuatro cosas medidas que no son obvias

**1. `uses: ./.github/actions/...` NO vale dentro de un reusable.** El `./` se
resuelve contra el repo que **llama**, no contra este, así que desde los 37
consumidores esa ruta no existe. Va la absoluta:
`pocharlies-org/k8s-gitops-pocharlies/.github/actions/notify-telegram@main`.

**2. Los secretos de ORG no llegan a los repos PRIVADOS en plan free.**
Comprobado: `TELEGRAM_CI_BOT_TOKEN` con `visibility=all` llega **vacío** a un
repo privado. Y 13 de los 37 consumidores lo son. Por eso el token va con
fallback:

```yaml
token:   ${{ secrets.TELEGRAM_CI_BOT_TOKEN || secrets.OPENCLAW_TELEGRAM_BOT_TOKEN }}
chat_id: ${{ secrets.TELEGRAM_CI_CHAT_ID  || secrets.OPENCLAW_TELEGRAM_TARGET }}
```

**3. El `thread_id` va EN CLARO, no en un secreto.** Un id de topic no es una
credencial: no abre nada por sí solo. Y como secreto de organización no llegaba
a los privados (ver 2). `OPENCLAW_TELEGRAM_THREAD_ID` apunta a un thread del
grupo **viejo** de OpenClaw: probado en vivo, Telegram devolvía
`400 message thread not found`.

**4. `strict: 'true'` hace su trabajo.** Ese 400 salió como paso **rojo**, y por
eso se cazó antes de dejarlo tocando 37 repos. En los reusables va a `false` a
propósito: un aviso perdido no puede tumbar un job que ya está rojo por otra
razón, y el paso deja `::warning::` igualmente.

## Lo que la acción NO hace

**No averigua qué paso falló.** `reusable-ci` lo calcula aparte consultando
`/actions/runs/<id>/jobs` y se lo pasa en el texto, porque es lo más útil del
aviso: sin eso hay que abrir el run para saber qué se rompió. Ese paso lleva
`continue-on-error` — un adorno no puede impedir que se notifique.

Si algún día más llamantes lo necesitan, ese cálculo debería mudarse aquí.

## Historia, para no repetir el error

Había **cinco** copias de este notificador, una por reusable, ~90 líneas de JS
inline cada una. Cinco copias divergen: en este mismo sistema la puerta de
marcas del `.app` se quedó con seis marcas cuando las buenas eran cuatro, y
nadie lo vio hasta que alguien las comparó. Unificarlas quitó **472 líneas**.

Queda una **sexta** copia en `synapse/.github/workflows/ci.yml`, deliberada: ese
repo no consume estos reusables y su comentario explica que quiere un ping
compacto. No se toca sin leerlo antes.

El camino de webhook a OpenClaw se retiró: `OPENCLAW_GITHUB_NOTIFY_URL` no
estaba configurado **ni en el repo ni en la organización**, así que
`postWebhook()` devolvía `false` siempre y todo iba por Telegram desde el
principio.
