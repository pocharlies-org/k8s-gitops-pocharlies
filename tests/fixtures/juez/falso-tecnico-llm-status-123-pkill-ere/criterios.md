# DGX-782 · 00-spec
Rol: cto · Fecha: 2026-10-09 · Sesión: 6755b999-83b3-45b0-a9c9-0b9f817e83ba · Estado: LISTO

Historia H2 de la épica DGX-774. Dueño: developer. Plan: 10-plan.md de DGX-774 (sección H2), con las condiciones de nota-architect-plan.md y nota-security-ci-y-rutas.md. Diseño: handoff `Design/claude-design/dgx-770-inferencia-cuentas-handoff.md` (llm-status-ios, 8c40c2e).

Partes (una PR cada una). Cada PR declara en «Alcance de esta PR» los criterios que cubre con su número de orden en esta lista (C1 es el primero), que es como los numera el juez:
- H2-a: C1, C2, C3 y C16. H2-b2: C4 a C9 y C16. H2-b3: C10, C11, C15 y C16. H2-b1: C12 y C16. H2-c: C13, C14, C15 y C16.

Partes:
- H2-a · dgx-infra (master): contratos por ruta y paridad web↔app.
- H2-b1 · llm-status-ios (main): workflow `app-pruebas.yml` en el runner `nexus-mac-pruebas` (espera a DGX-784).
- H2-b2 · llm-status-ios: reglas de inferencia en DGXKit, sin vistas.
- H2-b3 · llm-status-ios: navegación, barra lateral del iPad, StateCard, stub y UITests.
- H2-c · llm-status-ios: Peticiones por LLM, vLLM Servers, GPU y Fleet con sus detalles.

Criterios de aceptación:
- [ ] Contratos (H2-a): cada ruta de lectura que consume la app tiene su entrada `dgx.<área>.<cosa>.v1` en `CONTRACTS.yaml` (kind http-route, publisher, files, active, note con las claves), marcador `# CONTRACT:` en su ruta, línea en `tests/fixtures/app_endpoints.json` y un test guardián de sus claves.
- [ ] Paridad (H2-a): `app-parity-inferencia.test.js` corre en el job `dashboard-tests` y compara filtros, ventanas, orden de cuentas y registro de secciones de la web con los goldens de `tests/fixtures/app-parity/`.
- [ ] Rutas con SSO (H2-a): ninguna ruta se abre ni se proyecta; las que dan 302 en LAN quedan anotadas y la app las llamará con Bearer por `DGX.send`.
- [ ] Por motor (H2-b2): `LLMGroupsTests.testAgrupaPorMotorNoPorDueño` pasa: los grupos son Head DGX2, Lab DGX3 y Alibaba con los conteos de la fixture.
- [ ] Filtros (H2-b2): `RequestFiltersTests.testCincoFiltrosIgualQueLaWeb` pasa contra el golden vendorizado de dgx-infra, con selección múltiple.
- [ ] Rendimiento (H2-b2): `RequestFiltersTests.testUnIndicePorInstantanea` pasa (`EngineIndexCache.builds == 1` al recorrer los cinco filtros).
- [ ] Enlaces (H2-b2): `ReqLinksTests.testEnlacesSoloTerminadasYSoloHttp` pasa.
- [ ] Registro (H2-b2): `SeccionesTests.testRegistroIgualQueLaWeb` pasa (17 secciones, ids y orden de la web).
- [ ] Estados (H2-b2): `EstadoPantallaTests.testTablaDeEstados` pasa y los estados siguen `Design/DESIGN.md` §4.4 (un fallo no cambia el layout).
- [ ] Barra lateral (H2-b3): `NavegacionUITests.testBarraLateralConTodasLasSecciones` pasa en iPad Pro 13 horizontal y vertical y en iPadOS 17 con `-dgxLegacyTabs`: DGX Spark lista 11 secciones, Routing 6, y cada fila abre su pantalla.
- [ ] Navegación (H2-b3): Entrada, Secciones, Avisos, Ordenar y el enlace entre pestañas como en el handoff; Pagos, el contador de Compañía y el Mac siguen funcionando.
- [ ] CI (H2-b1): el workflow de pruebas corre `swift test` y los builds de `LLMStatus` y `LLMStatusMac` en la PR, en `nexus-mac-pruebas`, sin secretos ni firma, y falla si `swift test` no ejecuta tests.
- [ ] Pantalla (H2-c): `PeticionesUITests.testTodasNoCuelga` pasa (600 filas, la lista aparece en ≤ 2 s) y las peticiones salen separadas por LLM con filtros y su detalle.
- [ ] Pantallas (H2-c): vLLM Servers, GPU y Fleet con detalle de servidor, nodo y runtime, con datos en vivo, sin una segunda lista de peticiones (`RequestsView` se sustituye).
- [ ] Accesibilidad: estilos de texto del sistema, Dynamic Type hasta accesibilidad, etiquetas de VoiceOver y táctiles ≥ 44 pt en toda pantalla nueva.
- [ ] Ningún fichero del diff de una PR supera ~30 KB: fixtures recortadas a los campos que leen las reglas; lo grande se genera en el test.
