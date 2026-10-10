DGX-782: navegación por secciones, barra lateral del iPad, estados y stub (H2-b3)

## Qué cambia

Parte H2-b3 de DGX-782 (épica DGX-774): la navegación por secciones de DGX Spark y Routing, la barra lateral del iPad, el componente de estados y las herramientas de prueba. Las reglas puras (registro de secciones, filtros, estados) son de H2-b2 (#121); aquí solo lo que pinta o recorre la app. Los destinos de cada grupo apuntan a las pantallas de hoy; las nuevas son de H2-c y H3 y entran sin tocar el fichero de otra parte.

- **Navegación.** `SegmentTab` da a «inferencia» la Entrada (`EntradaView`) y a «routing» la `RoutingTab`. iPhone: la Entrada lleva «Secciones» arriba y «Todas las secciones» abajo; «Secciones» lista las 11 secciones en sus tres grupos con «Ordenar» y la fila «Cuentas y cuotas», que cambia a la pestaña Routing y lo dice; Routing abre directamente sus seis secciones en tres grupos, con «Secciones de DGX Spark» al pie. «Avisos» (recuento y caídos de `/api/service-health`) abre la pantalla de estado del servidor, que ya existe: la de Avisos propia espera su fuente (hallazgo 13 del architect). «GPU y Fleet» es una sola fila. «Ordenar» es una hoja con flechas de 44 pt por grupo y «Restablecer orden»; se guarda en el dispositivo, una lista por pestaña, con las claves de la web.
- **Barra lateral del iPad** (`SeccionesSidebar.swift`). Vive dentro de la pestaña, nunca en `RootTabs`. iOS 18+: un `NavigationSplitView` dentro de la pestaña de la `TabView` `.sidebarAdaptable`; en vertical se pliega y el botón «Secciones» la abre encima. iPadOS 17 (`-dgxLegacyTabs`, el iPad de la casa): la rama `NavigationSplitView` de `RootTabs` pasa a tres columnas (segmentos · secciones · pantalla) solo para DGX Spark y Routing; el resto de pestañas y Pagos, el contador de Compañía y el Mac no cambian. `TabSection` (hallazgo 16) no vale: no puede llevar «Ordenar», la fila Avisos con su recuento, grupos que se pliegan ni el enlace a la otra pestaña.
- **`StateCard`** (`Screens/Inferencia/StateCard.swift`, se construye desde `EstadoPantalla` de H2-b2): el único sitio que pinta cargando, vacío, no residente, error de una cifra, dato viejo y sin conexión, según `Design/DESIGN.md` §4.4 (un fallo no cambia el layout; vacío y no residente son `ContentUnavailableView`; nunca rojo; identificador `estado.TIPO`).
- **Stub.** `Tools/stub_common.py` (argumentos, `/__log`, `/__mode`, `/__reset`) se extrae de `pagos-stub.py` y `session-rows-stub.py`, que lo usan; `Tools/inferencia-stub.py` se monta sobre él con los modos `vivo`, `vacio`, `error`, `viejo`, `noresidente` y `carga`, sirve cualquier `/api/…` de `Tools/fixtures/inferencia/MODO/` y reproduce el SSE. Fixtures: capturas reales del 09-10 sin UUID reales ni IPs (`capturar.py` las sanea y las recorta; la mayor pesa 28 KB).
- **UITests.** Target `LLMStatusUITests` en `project.yml` (solo XCTest de Apple; ni `testflight.sh` ni el archive lo incluyen), `NavegacionUITests.testBarraLateralConTodasLasSecciones`, `CaptureTour` y `Scripts/qa-tour.sh` (galería de capturas por aparato, orientación y apariencia, con una pasada de texto grande). `-dgxScreen` y `-dgxAppearance` solo existen bajo `#if DEBUG`.
- **Accesibilidad.** Estilos de texto del sistema, `.dynamicTypeSize(...accessibility3)`, filas y botones de 44 pt como mínimo, etiquetas de VoiceOver y el tono siempre con su palabra.
- **`ARCHITECTURE.md`**: el texto del architect (decisión de DGX-774, componentes compartidos, tests, CI/CD) y la línea de las rutas con SSO corregida (R5 de security).

## Alcance de esta PR

- C10: `NavegacionUITests.testBarraLateralConTodasLasSecciones` (DGX Spark 11 secciones, Routing 6, cada fila abre su pantalla, el enlace a la otra pestaña) en horizontal y vertical; pasa en iPad Pro 13 iOS 26. La configuración de iPadOS 17 con `-dgxLegacyTabs` está escrita y va en «Fuera de la puerta».
- C11: Entrada, Secciones, Avisos, Ordenar y el enlace entre pestañas; Pagos, el contador de Compañía y el Mac siguen compilando y funcionando.
- C15: estilos de texto del sistema, Dynamic Type hasta accesibilidad, etiquetas de VoiceOver y táctiles de 44 pt en lo nuevo.
- C16: ningún fichero del diff pasa de ~30 KB.

## Pruebas

Sobre el head de esta rama, en el MacBook de compilaciones (Xcode 26.6). Detalle en `.company/evidence/DGX-782-navegacion.md`.

- `swift test --package-path Packages/DGXKit`: `Executed 110 tests, with 0 failures (0 unexpected)`.
- `xcodebuild build` de `LLMStatus` (`generic/platform=iOS Simulator`): `** BUILD SUCCEEDED **`.
- `xcodebuild build` de `LLMStatusMac` (`generic/platform=macOS`): `** BUILD SUCCEEDED **`.
- `Scripts/qa-tour.sh --device "DGX782 iPad Pro 13 iOS26" --test navegacion`: `Executed 2 tests, with 0 failures (0 unexpected)` (`testBarraLateralConTodasLasSecciones` en horizontal y vertical, y `testPagosSigueAbriendoDesdeLaNavegacion`). La primera pasada falló en vertical porque la prueba esperaba la barra de la pestaña a la que lleva el enlace, que en vertical llega plegada; ahora la abre antes de esperarla (la app no cambia).
- `company-duplicados`: sin duplicación nueva.

## Fuera de la puerta

Verificación de qa en la vuelta de capturas (no es de esta PR):

- La prueba de la barra lateral en iPadOS 17 con `-dgxLegacyTabs` (simulador de iPad Pro 12.9 con iOS 17.5). La última vez cayó con `Lost connection to the application` (`XCTAutomationSupport`, `runtime_issue_os_log_fault_callback`): el simulador en español inunda el log de accesibilidad y, pasada la cuota, cierra la app. La prueba ya relanza la app en cada grupo y la nota está en `Scripts/qa-tour.sh`; falta repetirla.
- Las capturas de la barra lateral en las tres configuraciones (iPad Pro 13 iOS 26 horizontal y vertical, iPadOS 17 con `-dgxLegacyTabs`), con `Scripts/qa-tour.sh --test tour`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

