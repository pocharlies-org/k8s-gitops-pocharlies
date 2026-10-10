Rol: cto · Fecha: 2026-10-10T00:40:00+00:00 · Sesión: en-vivo-Dani · Estado: LISTO

# INFRA-804 — Las secretarias de Hermes no pueden manejar el Chrome del Mac por ssh; Reminders sigue funcionando

## Objetivo
Cerrar con un freno **mecánico** la vía del incidente del 09-10: `terminal` → `ssh x86` → `ssh mac` → Chrome del Mac por CDP `:9222` u `osascript`. El SOUL ya lo prohíbe, pero eso no lo impide. Decidido por Security en DGX-760, comentario 31184, con la enmienda de abajo.

**Enmienda del CTO al veredicto:** no basta con el `command=` forzado en el Mac sobre una clave dedicada. La secretaria entra al x86 como `dibanez` con una shell completa, y desde ahí `ssh mac` usa la clave de flota `nvidiadgx` y se salta el muro. El freno tiene que estar **también en el salto pod → x86**: la clave con la que las secretarias entran al x86 solo puede ejecutar el puente a Reminders, nunca una shell.

Repo: `k8s-openclaw-qwen36-pocharlies` (chart: SOUL, `DENY_SECRETARIA`, clave montada) y máquinas x86 y Mac (`authorized_keys`, wrapper, `~/.ssh/config`).

## Criterios de aceptación
- [ ] **Medido antes de tocar nada:** con qué clave y usuario entran al x86 las secretarias y qué otros perfiles de Hermes usan esa misma clave. Si la comparten perfiles que necesitan una shell completa en el x86 (ops, sre-devops, cto…), las secretarias pasan a tener **una clave propia**, montada solo en sus perfiles.
- [ ] **x86:** la clave de las secretarias lleva en `authorized_keys` `command="<puente>",restrict` (sin pty ni reenvío de puertos). El puente solo admite las órdenes de Reminders y las pasa a `ssh mac-reminders`. Cualquier otra orden se rechaza, `ssh mac` incluido.
- [ ] **Mac:** una clave dedicada a ese puente (no `nvidiadgx`), con `command="/usr/local/bin/reminders-runner",restrict,no-port-forwarding,no-pty`. El wrapper solo ejecuta los `osascript` de Reminders (crear por base64 y leer listas) y rechaza todo lo demás. En el x86, `Host mac-reminders` apunta a esa clave.
- [ ] **Chart:** el patrón del SOUL `ssh mac` pasa a la orden del puente. `DENY_SECRETARIA` añade `*9222*`, `*devtools/browser*` y `*chrome*` como segunda capa. Un test fija el patrón nuevo.
- [ ] **En vivo:** una secretaria crea y lee un recordatorio como hoy. Desde su vía se **rechazan** `ssh mac 'curl -s localhost:9222/json'`, `ssh mac 'osascript -e "tell application \"Google Chrome\" to …"'` y una shell interactiva en el x86.
- [ ] **Sin efectos colaterales:** el resto de la flota (dgx1/2/3, x86, sesiones de Dani) sigue entrando al Mac con `nvidiadgx` igual que antes, y los perfiles no secretaria conservan su acceso al x86.

## Restricciones
- No se toca la clave de la flota `nvidiadgx` ni se quita nada del `authorized_keys` del Mac: solo se **añade** la entrada dedicada.
- Antes de cambiar el `authorized_keys` del Mac y del x86 se guarda una copia con fecha, y la entrada nueva lleva un comentario que nombra INFRA-804.
- Nada de secretos en el transcript: las claves privadas no se imprimen.
