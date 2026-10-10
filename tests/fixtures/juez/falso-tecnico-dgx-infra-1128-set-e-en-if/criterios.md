Rol: it · Fecha: 2026-10-09T21:05:00Z · Sesión: 9b2e04f6-4313-42ad-a460-510fa234563e · Estado: LISTO

# DGX-784 — Runner de pruebas `nexus-mac-pruebas` en el Mac para las PR de llm-status-ios

Request IT suelta (sin épica propia): la pide el veredicto de security de DGX-774
(`nota-security-ci-y-rutas.md`). El workflow de pruebas de PR (H2-b de DGX-782) ejecuta
código de PR y no puede correr en el runner de despliegue `nexus-mac`, que tiene la
identidad Apple Distribution y el llavero de firma. Repo afectado: `dgx-infra` (script de
montaje); la máquina es el Mac de compilaciones (nexus-mac).

## Criterios de aceptación

- [ ] C1. `gh api repos/pocharlies-org/llm-status-ios/actions/runners` lista un runner
  **online** con la etiqueta `nexus-mac-pruebas` y **sin** la etiqueta `nexus-mac`.
  Comprueba: `gh api repos/pocharlies-org/llm-status-ios/actions/runners --jq '.runners[] | select(.name=="macbook-nexus-pruebas") | .status, ([.labels[].name])'`
  Esperado: `online` y `["self-hosted","macOS","ARM64","nexus-mac-pruebas"]`.
- [ ] C2. El runner corre bajo un usuario de macOS **sin admin**, con llavero propio y sin
  credencial de firma: como `runner-pruebas`, `security find-identity -v -p codesigning`
  devuelve **0 identidades válidas**; no existe `MAC_KEYCHAIN_PASSWORD` ni credencial Apple
  en ese usuario.
- [ ] C3. Como ese usuario responden `xcodebuild -version` y `xcrun simctl list devices`
  (Xcode completo vía `DEVELOPER_DIR`, sin tocar el `xcode-select` global), de modo que
  `swift test` y el `xcodebuild build` de simulador sin firma son posibles.
- [ ] C4. El runner de despliegue `nexus-mac` (`macbook-nexus-app`) sigue online y sin
  cambios, y el servicio del runner de pruebas sobrevive reinicios (LaunchDaemon con
  RunAtLoad/KeepAlive, no LaunchAgent de `svc.sh`).
- [ ] C5. El montaje queda documentado como script idempotente en el repo:
  `dgx-infra/scripts/mac-runner-pruebas.sh` (PR pocharlies-org/dgx-infra#1128), con la
  invocación desde el x86 en la cabecera.
