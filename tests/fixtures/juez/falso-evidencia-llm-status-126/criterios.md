# DGX-783 · 00-spec
Rol: cto · Fecha: 2026-10-09 · Sesión: 6755b999-83b3-45b0-a9c9-0b9f817e83ba · Estado: LISTO

Historia H3 de la épica DGX-774. Dueño: developer. Plan: 10-plan.md de DGX-774 (sección H3), con las condiciones de nota-architect-plan.md (hallazgos 3, 6, 8, 12, 13 y 17) y nota-security-ci-y-rutas.md (R1-R6). Diseño: handoff `Design/claude-design/dgx-770-inferencia-cuentas-handoff.md` (llm-status-ios) y las mejoras N1-N8 de nota-ux-mockup.md de DGX-774. Contratos de las rutas: dgx-infra#1127 (en producción). Base de la app: DGX-782 (navegación, StateCard, stub y reglas de DGXKit).

Decisión del CTO sobre Avisos (hallazgo 13 del architect): la fuente es `GET /api/service-health` (grupos y su estado) y `error_rate` de `GET /api/litellm/metrics/summary?range=24h`, las dos sin SSO en LAN y gemelas de los eventos `service_health` y `litellm_summary` del stream de actividad v3 (contrato `dgx.activity.stream`). Nada se calcula en cliente.

Partes (una PR cada una). Cada PR declara en «Alcance de esta PR» los criterios que cubre con su número de orden en esta lista (C1 es el primero), que es como los numera el juez:
- H3-a (Tráfico, gráficas y gateway): C1, C2, C3, C4, C5, C6, C12, C13 y C14.
- H3-b (pestaña Routing y Avisos): C7, C8, C9, C10, C11, C12, C13 y C14.

Criterios de aceptación:
- [ ] Tráfico (H3-a): `TraficoTests.testPorProveedorYVentanas` pasa con una fixture real de `/api/inference/traffic`: totales y porcentajes por proveedor de las ventanas 10 s, 1 min, 5 min y 1 h, y la auditoría Alibaba da sus 20 filas, cada una con su detalle (sesión con visor o «Sin visor»).
- [ ] Gráficas (H3-a): Calidad del decode y Rendimiento y GPU leen `/api/llm/series` con `ChartCard`; cada gráfica se amplía a pantalla completa, también en horizontal; la cifra «ahora» y la «media» se nombran distinto, como en el handoff.
- [ ] Refusal y Sources (H3-a): Refusal rates lee `/api/llm/refusal-rates` y su serie, con ventana, agrupación, censura, fuente y filtros de agente y modelo; Request Sources tiene su pantalla con el vacío «Sin datos de fuentes ahora».
- [ ] Gateway (H3-a): Model Routing lee `routing[]` del SSE (sin editar `LiveStore.swift`), reutiliza `ModelDetail` con las tres ventanas en el detalle; Consumidores lee `/api/litellm/consumers` con el detalle de alias de opencode.
- [ ] UI de H3-a: `GatewayUITests.testCadaDetalleSeAbre` pasa: desde la Entrada se llega a cada pantalla y detalle de H3-a (`seccion.ID`, `detalle.ID`).
- [ ] Estados de H3-a: con el stub en `vacio`, `error`, `viejo` y `noresidente`, cada pantalla de H3-a enseña su `StateCard` (`estado.TIPO`).
- [ ] Cuotas (H3-b): `CuotasTests.testMarcas95YRitmo` pasa contra `golden-cuotas.json` de dgx-infra; `Cuotas.swift` porta solo lo que la web calcula en cliente (`windowPace`, `textoMargen`, estados de `vistaDesvio` que dependen del reloj) y lee `orden`, `fuera`, `margen` y `desvio` de `observed.cuenta_claude` sin recalcularlos.
- [ ] Alibaba (H3-b): `AlibabaTests.testCuentasSalenDeLaLista` pasa: las cuentas salen de `/api/alibaba/accounts` (con tres cuentas, tres filas); Token Plan con su detalle de cuenta y Alibaba · modelos y coste de `/api/alibaba/catalog`.
- [ ] Uso por perfil (H3-b): `UsoPerfilTests.testSieteVentanasYOrden` pasa con una fixture real de `/api/litellm/uso-perfiles` (grupos y perfiles con sus siete ventanas, orden por tokens o por peticiones) y el detalle de perfil enseña sus peticiones en curso.
- [ ] Routing en solo lectura (H3-b): Claude · suscripciones (marcas del 95 % y del ritmo, «Ver», «Fuera del orden», acciones en el detalle de cuenta) y Modo, desvío y BURST leen `/api/company/control` y `/burst` con Bearer por `DGX.send`, distinguen 403 de «sin sesión» y no hacen ninguna escritura; OpenRouter en la raíz de Routing.
- [ ] Avisos (H3-b): la pantalla Avisos lee `/api/service-health` y el `error_rate` de `/api/litellm/metrics/summary?range=24h` (decisión de arriba), con grupos plegables, «Todo operativo» sin avisos y el enlace a Model Routing; `RoutingUITests.testCadaCuentaYDetalleSeAbre` pasa.
- [ ] Estados de H3-b: con el stub en `vacio`, `error`, `viejo` y `noresidente`, cada pantalla de H3-b enseña su `StateCard`.
- [ ] Accesibilidad: estilos de texto del sistema, Dynamic Type hasta accesibilidad, etiquetas de VoiceOver y táctiles ≥ 44 pt en toda pantalla nueva; las mejoras N1-N8 de la revisión UX que toquen la pantalla están resueltas.
- [ ] Ningún fichero del diff de una PR supera ~30 KB: fixtures recortadas a los campos que leen las reglas; lo grande se genera en el test.
