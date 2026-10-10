DGX-782: CI de pruebas de PR en nexus-mac-pruebas, sin firma ni secretos (H2-b1)

## Qué cambia
Añade `.github/workflows/app-pruebas.yml`: en cada PR contra `main` corre `swift test` de DGXKit y los builds de `LLMStatus` (iOS Simulator) y `LLMStatusMac`, sin firma ni secretos, en el runner propio `nexus-mac-pruebas` (usuario de macOS aparte, montado por DGX-784). Más una línea en `ARCHITECTURE.md` § CI/CD (la de la caché). El test que fallaba a propósito para ver el run rojo (`CiPruebaTests.swift`) ya está quitado del head; su run rojo está enlazado abajo.

Condiciones de security (`nota-security-ci-y-rutas.md`, 1-8) y hallazgo 4 del architect, una por una:
- `runs-on: [self-hosted, macOS, ARM64, nexus-mac-pruebas]`: nunca la etiqueta del runner de despliegue (job `Mac` de `app-deploy.yml`), para que las pruebas no le quiten el runner y `Nube` no lance un Xcode Cloud que no está activado.
- `on: pull_request` contra `main` y nada más (sin `pull_request_target`, `push`, `schedule` ni `workflow_dispatch`), más `if: github.event.pull_request.head.repo.full_name == github.repository`.
- `permissions: contents: read`, ninguna referencia a secretos, `concurrency: pruebas-${{ github.ref }}` con `cancel-in-progress`, `persist-credentials: false` en el checkout.
- Builds con `-destination 'generic/platform=iOS Simulator'` (sin `-sdk`) y `generic/platform=macOS`, ambos con `CODE_SIGNING_ALLOWED=NO`. Ningún paso toca el llavero ni firma.
- Paso permanente `swift test ejecutó pruebas`: falla si la salida de `swift test` no contiene `Executed [1-9][0-9]* tests`.
- Las XCUITest no están en el workflow: siguen a mano en este runner.

### Caché persistente (enmienda la condición 5 de security)
Por qué: el run 38003640643 (Mac cargado, en frío) tardó 55 min en `swift test` y el build de LLMStatus lo cortó el límite de 90. Security aprueba una caché persistente con las condiciones C1-C5 de `nota-security-cache-ci.md` (adjunta a DGX-782); sustituye al `-derivedDataPath "$RUNNER_TEMP/dd"` borrado al final que pedía la condición 5 de `nota-security-ci-y-rutas.md`. Todas aplicadas:
- **C1**: todo bajo `~/Library/Caches/dgx-pruebas/` del usuario del runner, `0700`, con `spm-cache/` (`swift test --cache-path`), `spm-cloned/` (`xcodebuild -clonedSourcePackagesDirPath`) y `dd/<slug>` (`-derivedDataPath` de los dos `xcodebuild`), con `slug` = nombre de la rama saneado (solo `[A-Za-z0-9._-]`, el resto a `-`, `/` incluido) + 8 hex del sha256 del nombre. Cae el `rm -rf` final del DerivedData.
- **C2**: DerivedData por rama, nunca por hash de `Package.resolved`. El nombre de la rama entra por `env` (`RAMA`), no interpolado en el guion.
- **C3**: al inicio, antes de compilar, se borran los `dd/<slug>` con mtime de más de 14 días (cada run toca el suyo, así que una rama viva no caduca) y, en la primera ejecución de cada semana ISO (marcador `.semana`), el árbol `dgx-pruebas/` entero.
- **C4**: tope de 25 GB entre `spm-cache`, `spm-cloned` y `dd`: se borra por mtime, primero `dd/` y luego `spm-*`, hasta caber; si el disco libre de `$HOME` baja de 20 GB se vacía `dgx-pruebas/` antes de compilar.
- **C5**: `timeout-minutes: 40` (la desviación a 90 min queda retirada).
- `Limpiar` conserva el `pkill` de procesos colgados, adaptado al camino nuevo: `pkill -u "$(id -u)" -f "$DGX_DD"`, patrón de cadena simple sin paréntesis ni alternancias (hallazgo del juez sobre `app-pruebas.yml:92`). No se lanza si `DGX_DD` está vacío (un patrón vacío casaría con todo el usuario). El camino del `dd` ya no puede casar con el guion `_temp/<guid>.sh` del propio paso.

DECISIÓN TOMADA: `swift test` compila con `--scratch-path "$DGX_DD/swift-test"`, dentro de `dd/<slug>`, igual que el `-derivedDataPath` de los dos `xcodebuild`. `--cache-path` solo guarda las descargas de SwiftPM; sin `--scratch-path` lo compilado (swift-openapi-runtime, DGXAPI generado: casi todo el tiempo de `swift test`) iría al `.build` del workspace, que el `git clean` del checkout borra en cada run. Al vivir en `dd/<slug>` hereda C1 (directorio 0700) y C2 (por rama), y la purga C3/C4 lo alcanza al borrar `dd/<slug>` entero. El `pkill -u "$(id -u)" -f "$DGX_DD"` de `Limpiar` también lo cubre: `swift test` y sus hijos llevan `$DGX_DD/swift-test` en la línea de órdenes. Se queda el nombre `swift-test` (no `swiftpm`): renombrarlo dejaría en frío el `.build` que el run 38013550701 ya ha llenado.

Riesgo conocido: la primera ejecución de la semana y la primera de una rama compilan en frío, y con 40 min un Mac muy cargado puede no bastar; sería un fallo a investigar (C5), no un timeout que se sube.

## Alcance de esta PR
- C12: el workflow de pruebas corre `swift test` y los builds de `LLMStatus` y `LLMStatusMac` en la PR, en `nexus-mac-pruebas`, sin secretos ni firma, y falla si `swift test` no ejecuta tests.
- C16: el diff es un fichero de workflow de ~130 líneas y una línea de `ARCHITECTURE.md`.

## Cómo se probó
- YAML válido (`yaml.safe_load`) y el paso permanente probado contra `Executed 110 tests, with 0 failures` (casa) y `Executed 0 tests` (no casa).
- El paso `Caché de compilación`, extraído del YAML y ejecutado con `bash -eo pipefail` sobre un `HOME` de pruebas: slug seguro con una rama hostil (`feat/DGX-782 ci; $(x)` da `feat-DGX-782-ci----x--cc6bde46`), directorio `0700`, un `dd` reciente se conserva, uno de 20 días se purga, el cambio de semana lo vacía todo, con el tope bajado a 300 KB borra `dd/` por mtime y deja `spm-*`, y con el disco libre simulado por debajo del mínimo vacía y reescribe el marcador.
- Prueba de que el job ejecuta de verdad (lección DGX-737): primer push con un test que falla a propósito, segundo sin él.
- Sin probar en local: los flags de macOS (`xcodebuild`, `pkill` BSD, `date +%G-%V`); los prueba el run del head.

## Runs de la prueba (DGX-737)
- **Rojo, el job ejecuta de verdad**: https://github.com/pocharlies-org/llm-status-ios/actions/runs/37995842077 sobre `2baa290` (con `CiPruebaTests.testFallaAProposito` dentro). Terminó en `failure` en el paso `swift test (DGXKit)`: «Executed 105 tests, with 1 failure», el test a propósito.
- Sin valor como prueba (cortados por el límite o del runner): 37993485215 (20 min), 37998433615 (40 min, `swift test` OK a los 18 min y build iOS cortado), 38002595033 (el runner perdió la conexión, 0 pasos), 38003640643 (90 min: `swift test` 55 min y build iOS cortado). Son la medida que motiva la caché. 38013550701 (intento 2, sobre `e545c69`): la caché de descargas sirvió (`Fetched … from cache`), pero `swift test` tardó 30 min porque el `.build` compilaba en frío: el log enseña que ya iba a `dd/DGX-782-ci-pruebas-27b5357e/swift-test`, y era la primera ejecución con esa ruta (el intento 1 no llegó a tener job). El build de iOS se cortó a los 40 min de C5. Ese `.build` ya está lleno, así que el run de este head debería ser el primero con `swift test` en caliente.
- **Verde**: pendiente del run del head de esta rama (`gh run list -R pocharlies-org/llm-status-ios --branch DGX-782-ci-pruebas`); se enlazará aquí cuando termine.

## Fuera de la puerta
- El resultado de los runs (rojo, luego verde) es del run de esta PR, no del diff: `gh run view` sobre el head.
- El aislamiento del usuario de macOS del runner (sin identidad de distribución, sin llavero de firma) lo monta devops en DGX-784; el diff no puede demostrarlo.
- Que la caché acorte de verdad los runs (segundo run de la rama) es una medida en el Mac, no del diff.

🤖 Generated with [Claude Code](https://claude.com/claude-code)


