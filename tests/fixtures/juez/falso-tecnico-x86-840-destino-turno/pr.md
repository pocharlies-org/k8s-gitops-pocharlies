SC-2212: el bus espera al hook Stop — un cierre bloqueado no es cierre y bus-medida cuenta ESPERA en su cubo

## SC-2212: el bus espera al hook `Stop` — el bloqueo aterriza y `bus-medida` cuenta `ESPERA` en su cubo

Reapertura de SC-2212 por el NO PASA de qa de la épica SC-2209 (`70-qa.md`, id 24313). Medido (sid `91c03b43`, pm de
SC-2171): el hook bloqueó el cierre sin `ESTADO:` a las 15:57:29.469Z y el journal del bus, ~3 s después, decía «turno
cerrado (sin ESTADO), a nadie; unidad parada» sin continuación en el transcript: el bus daba por cerrado el turno cuyo
último evento era el `stop_hook_summary` del propio bloqueo y paraba la unidad antes de que el rol escribiera su línea.
La contraprueba (`3f12964d`) sí continuó (a los 9 s) y cerró con `ESTADO: ENTREGA`: el bloqueo aterrizaba solo cuando el
bus no cazaba la ventana.

- `company_capacidad`: al bloquear, el hook deja una marca por sesión (`bots/stop-bloqueo/<sid>`, contenido: el
  `id_turno` que bloqueó). `turno_cerrado_de` — el criterio canónico que usan bus, `company-sesion`, despertador y
  encargos — no da por cerrado el turno mientras la marca señale el último y no hayan pasado `STOP_BLOQUEO_S` (120 s);
  sin continuación tras el tope, cierra sin ESTADO como antes. La gramática de `ESTADO:` no se copia.
- `company_bus.turnos_cerrados`: un cierre con `ESPERA:` vigilable (`despertador.esperas_de`, la misma del hook) se
  etiqueta `ESPERA` en el journal: `company-ctl bus-medida` lo cuenta en su cubo y no como «sin ESTADO» (de los 21
  turnos sin ESTADO en 3 h de la medida de qa, 10 llevaban `ESPERA:` válida).
- El mismo race en los otros dos consumidores directos: `company-sesion.esperar_turno` espera la continuación (antes
  devolvía el texto previo al bloqueo), y `company_desatascador.turno()` pasa a `turno_cerrado_de` en vez de duplicar el
  criterio.
- Tests que fallan antes del arreglo: `BloqueaStopHook` (bus y capacidad), `MarcaBloqueo` (hook), cubo `ESPERA` en
  `BusMedida`. Suite completa del repo, un fichero por proceso: evidencia en `.company/evidence/sc-2212-bus-espera-al-hook.md`.

## Alcance de esta PR

- C4: el hook `Stop` (cuándo bloquea) extiende su bloqueo con la marca por sid y turno (`marcar_stop_bloqueo`,
  best-effort: si el escritorio falla el bloqueo se emite igual); el bus, `esperar_turno` y el desatascador no dan por
  cerrado un turno cuyo último cierre bloqueó el hook hasta la continuación o el tope `STOP_BLOQUEO_S` (120 s), y tras
  él cierra sin ESTADO como antes.
- C6: `ARCHITECTURE.md` documenta la marca, la espera en `turno_cerrado_de` y el cubo `ESPERA` de `bus-medida`.
- Defecto H2 del `70-qa.md` de SC-2209 que reabre la historia: `company-ctl bus-medida` cuenta un cierre con `ESPERA:`
  vigilable en su propio cubo (`ESPERA`), no como «sin ESTADO» — el criterio de ≤ 10/día lo admite.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

