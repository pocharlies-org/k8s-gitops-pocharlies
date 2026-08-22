# Notificadores retirados — 22-08-2026

Aquí está lo que se **eliminó**, no lo que se evaluó. El código vivo es
`.github/actions/notify-telegram`; esto es el archivo, por si alguien busca
"¿dónde fue a parar aquel curl?".

## Qué había, y dónde

| dónde | qué era | estado |
|---|---|---|
| `reusable-ci.yml` | ~200 líneas de `github-script`: webhook + fallback Telegram + scraping de logs | **eliminado** |
| `reusable-release.yml` | ~90 líneas, misma forma | **eliminado** |
| `reusable-deploy-stg.yml` | ~90 líneas, misma forma | **eliminado** |
| `reusable-manifest-release.yml` | ~90 líneas, misma forma | **eliminado** |
| `reusable-manifest-pr-release.yml` | ~90 líneas, misma forma | **eliminado** |
| `release.yml` (este repo) | pasaba `OPENCLAW_GITHUB_NOTIFY_*` a los reusables | **eliminado** |
| `synapse/.github/workflows/ci.yml` | webhook compacto propio | **eliminado** |
| `k8s-openclaw-*` (6 bloques) | `curl` directo a la Bot API | **eliminado** (por la sesión k8s-7b) |

Total en este repo: **-472 líneas**.

## Por qué se pudo borrar el webhook sin perder nada

`OPENCLAW_GITHUB_NOTIFY_URL` **no estaba configurado ni en los repos ni en la
organización**. Comprobado con `gh secret list` y con la API de secretos de org.
Como el código hacía `if (!url) return false;` y Telegram era el respaldo,
**todas** las notificaciones iban ya por Telegram. El "primer camino" llevaba
meses muerto.

Se retiraron con él 7 declaraciones de secretos que ya no leía nadie:
`OPENCLAW_GATEWAY_URL`, `OPENCLAW_GATEWAY_TOKEN`,
`OPENCLAW_ALLOW_INSECURE_PRIVATE_WS`, `OPENCLAW_IDENTITY_B64`,
`OPENCLAW_TELEGRAM_ACCOUNT`, `OPENCLAW_GITHUB_NOTIFY_URL`,
`OPENCLAW_GITHUB_NOTIFY_TOKEN`.

## Lo único que se conservó del código viejo

`reusable-ci` calculaba **qué paso concreto falló** consultando
`/actions/runs/<id>/jobs`. La acción compartida no hace eso y es lo más útil del
aviso: sin ello hay que abrir el run. Vive ahora como paso propio
(`Que paso se rompio`) con `continue-on-error` — un adorno no puede impedir que
se notifique.

## Si hay que volver atrás

Todo está en el historial: `git log --follow .github/workflows/reusable-ci.yml`.
El commit de la migración es `dd9727e`. Pero antes de revertir, léase esto: el
webhook al que apuntaba **no tiene URL configurada**, así que revertir no
recupera un camino que funcionara.

## Secretos que ya se pueden borrar del repo

No los he borrado — son tuyos y borrar un secreto no se deshace:

- `OPENCLAW_TELEGRAM_BOT_TOKEN` y `OPENCLAW_TELEGRAM_TARGET`: aún se usan como
  **fallback** en los reusables, por si algún repo privado no ve los de la
  organización. Cuando `TELEGRAM_CI_*` esté en todos, sobran.
- `OPENCLAW_TELEGRAM_THREAD_ID`: **ya no se usa**. Apuntaba a un thread del
  grupo viejo y Telegram devolvía `400 message thread not found`. Este sí se
  puede borrar hoy.
