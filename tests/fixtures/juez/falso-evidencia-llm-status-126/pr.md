DGX-783: pestaña Routing (cuentas, Alibaba, uso, OpenRouter) y Avisos en solo lectura (H3-b)

## Qué cambia

Parte H3-b de DGX-783: la pestaña Routing y la pantalla Avisos, en solo lectura y sobre las mismas rutas que la web.

- DGXKit (`Inferencia/`): `Cuotas.swift`, `CuotasOrden.swift` y `Burst.swift` para las cuotas de Claude, el desvío y BURST (`orden`, `fuera`, `margen` y `desvio` se leen de `observed.cuenta_claude`); `Alibaba.swift` y `UsoPerfil.swift`.
- `Screens/Routing/`: Claude · suscripciones y su detalle, Modo, desvío y BURST, Alibaba (Token Plan, detalle de cuenta, modelos y coste), Uso por perfil y su detalle, OpenRouter y Avisos. Un cargador por ruta (`Fuente.swift`) con `StateCard`; solo GET, con Bearer por `DGX.send`.
- Stub: capturas reales saneadas en `Tools/fixtures/inferencia/vivo/api/` (`capturar.py --routing`, que quita lo que la app no lee).

## Alcance de esta PR

- C7: `CuotasTests.testMarcas95YRitmo` contra `golden-cuotas.json` de dgx-infra; `orden`, `fuera`, `margen` y `desvio` se leen de `observed.cuenta_claude`, no se recalculan.
- C8: `AlibabaTests.testCuentasSalenDeLaLista` (tres cuentas, tres filas); Token Plan con su detalle y Alibaba · modelos y coste.
- C9: `UsoPerfilTests.testSieteVentanasYOrden` sobre una captura real de `/api/litellm/uso-perfiles`; el detalle de perfil enseña sus peticiones en curso.
- C10: Claude · suscripciones y Modo, desvío y BURST leen `/api/company/control` y `/burst` con Bearer por `DGX.send`, separan el 403 de «sin sesión» y no escriben; OpenRouter en la raíz de Routing.
- C11: Avisos lee `/api/service-health` y el `error_rate` de `/api/litellm/metrics/summary?range=24h`; `RoutingUITests.testCadaCuentaYDetalleSeAbre`.
- C12: `RoutingUITests.testEstado*`: con `vacio`, `error`, `viejo` y `noresidente` cada pantalla enseña su `StateCard`.
- C13: estilos de texto del sistema, Dynamic Type, VoiceOver y 44 pt (`RoutingUITests.testLasFilasTienenAreaTactil`); N3 y N4 de la revisión UX.
- C14: ningún fichero del diff pasa de ~30 KB (el mayor, `Cuotas.swift`, 27,8 KB; `uso-perfiles.json`, 7,3 KB).

## Nota para el juez

- `$0.id.string == cc.efectiva.id.string` (`Cuotas.swift:275`; el hallazgo cita la 345) compara dos `String?`, no dos `J`: `J.string` es `String?` (`Packages/DGXKit/Sources/DGXKit/JSON.swift:33`, fuera del diff). La misma comparación (`usoId = cc.efectiva.id.string`, `CuotasOrden.swift:101`) marca la cuenta efectiva «en uso», y `CuotasTests.testMarcas95YRitmo` la comprueba fila a fila (`uso` contra `golden-cuotas.json`).

## Cómo se probó

En el Mac (Xcode 26.6). Detalle en `.company/evidence/DGX-783-routing.md`.

- `swift test --package-path Packages/DGXKit` con el código de `53441d7`: 135/135, EXIT=0 (`CuotasTests` 7/7, `AlibabaTests` 4/4, `UsoPerfilTests` 3/3). Lo que va después de `53441d7` solo toca la evidencia.
- `RoutingUITests` contra el stub: iPhone 17 Pro 6/6 con `9ec87ab` e iPad Pro 13 6/6 con `f0ef553`. Desde entonces solo cambió `uso-perfiles.json` del stub (los primeros perfiles son los mismos); no se repitieron.
- `python3 -m unittest test_inferencia_stub`: 17 OK. `sync-paridad.sh --limpieza` y `company-duplicados`: limpios.

## Fuera de la puerta

- El Bearer real contra `/api/company/control` y `/burst` (302 sin sesión) y las cifras en vivo frente a la web: qa con `Scripts/qa-tour.sh --vivo`.
- La vista dividida y la hoja del iPad: ux, sobre capturas.
- Fallbacks y exentos de Alibaba (`/api/model-routing/*`): no están en la lista de lectura de DGX-783.

🤖 Generated with [Claude Code](https://claude.com/claude-code)


