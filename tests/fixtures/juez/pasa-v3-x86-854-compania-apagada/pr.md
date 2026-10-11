SC-2295: compañía apagada no lanza ni reanuda nada

Con la compañía apagada (fichero `jira-trigger/apagada`) ya no nace ni se reanuda ninguna sesión ni turno nuevo.

Una sola regla, `company_encargos.apagada_para`, aplicada en los puntos compartidos:
- `jira-epic-trigger._lanzar`: sesiones de Claude CLI (supervisor, relanzar, bus).
- `company_encargos._unidad_turno`: turnos de Hermes y el buzón de `company_synapse`.
- `company-sesion lanzar` y `mensaje` a una sesión parada: niegan antes de crear sid (exit 3, «compañía apagada»).

Lo que ya corre sigue. Un mensaje a una sesión viva se entrega. Un rechazo sale como «sin hueco» con `--codigos`, así que el encargo se reintenta al encender y no va a Hermes como excepción. Las Acciones (ACC) y la secretaria no cambian.

`CONTRACTS.yaml`: nota sin cambio de valor en `cli.company-sesion.lanzar.en-vivo` y `.mensaje.en-vivo` (`Contract-Change: migrate`).

## Alcance de esta PR
- C1: `company-sesion lanzar` con la compañía apagada responde NO, exit 3, «compañía apagada», sin sid ni unidad.
- C2: `company-sesion mensaje` a una sesión parada no la reanuda; a una viva, se entrega.
- C3: bus, orquesta y `relanzar_duenos` no arrancan `ses-*` ni `turno-*`; el encargo queda pendiente.
- C4: rol `secretaria` y claves ACC sin cambios con la compañía apagada.
- C5: sin `apagada`, las suites existentes siguen en verde.

## Pruebas
Herméticas, con `HOME` temporal y `STATE_DIR` temporal. Medido: company-sesion 228 OK, company-encargos 99 OK, jira-epic-trigger 791 OK, y en verde company-bus, bus-poda, bus-turnos, bots, requests, vigilante, capacidad y burst. `company-duplicados`: sin duplicación nueva.

Ronda de hallazgos del juez: `_unidad_turno` ya no asigna con morsa dentro de un `or` (la forma del hallazgo; el bloqueo ya salía igual con la guarda de pruebas, y el test lo fija). Los tres lambdas de `_unidad_turno` en test_company_buzon aceptan `perfil, key`. Medido: test_company_buzon + encargos + sesion = 350 OK; los fallos de bots/piezas/aprobar/encargos en discover local también salen en origin/main (entorno del host, no de este cambio).

🤖 Generated with [Claude Code](https://claude.com/claude-code)


