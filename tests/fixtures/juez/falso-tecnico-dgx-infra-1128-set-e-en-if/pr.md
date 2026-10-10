DGX-784: runner de pruebas nexus-mac-pruebas en el Mac (script de montaje)

## Qué

Script `scripts/mac-runner-pruebas.sh` que monta (y re-monta, idempotente) la segunda instancia del actions-runner de `pocharlies-org/llm-status-ios` en el Mac de compilaciones:

- usuario macOS estándar `runner-pruebas\** (sin admin, llavero propio, sin identidad de firma ni `MAC_KEYCHAIN_PASSWORD`);
- runner 2.337.0 con etiquetas `self-hosted,macOS,ARM64,nexus-mac-pruebas` — **nunca** `nexus-mac` (esa es del runner de despliegue, DGX-756/DGX-774);
- servicio como **LaunchDaemon** (`UserName=runner-pruebas`, RunAtLoad+KeepAlive), porque el LaunchAgent de `svc.sh` no arranca para un usuario sin sesión GUI;
- `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer` en `.env` y en el plist (`xcode-select` del sistema apunta a CommandLineTools).

Ya ejecutado en vivo (DGX-784): `macbook-nexus-pruebas` online, `security find-identity -v -p codesigning` → 0 identidades, `xcodebuild -version` → Xcode 26.6, `xcrun simctl list devices` responde. El runner de despliegue `macbook-nexus-app` intacto.

## Por qué en el repo

Condición vinculante del veredicto de security de DGX-774 (nota-security-ci-y-rutas.md): el workflow de pruebas de PR (H2-b de DGX-782) corre código de PR y no puede pisar el runner de despliegue. Sin script, el re-montaje tras un reset del runner sería un incidente de una tarde.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
