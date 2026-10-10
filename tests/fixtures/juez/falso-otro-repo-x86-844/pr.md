INFRA-804: Reminders de las secretarias por un puente con orden forzada (x86 y Mac)

## Qué cambia

Las secretarias de Hermes llegaban al Mac de Dani con una shell completa en cada salto (pod → x86 → Mac). Desde ahí se podía manejar el Chrome del Mac por CDP `:9222` u `osascript`. Esta PR versiona las dos órdenes forzadas que ahora ata cada clave dedicada a una sola cosa, Apple Reminders:

- `libexec/reminders-bridge` es la orden forzada (`command=…,restrict`) de la clave `hermes-secretaria-x86` en el `authorized_keys` del x86. Admite `reminders <base64>` o `reminders` con el guion por stdin, y lo reenvía a `ssh mac-reminders`. Rechaza `ssh mac …`, `curl`, una shell interactiva y cualquier otra orden con salida 2, y deja una línea en syslog.
- `libexec/reminders-runner` es la orden forzada (`command=…,restrict,no-port-forwarding,no-pty`) de la clave `hermes-secretaria-mac` en el Mac. Solo ejecuta `osascript -` con un guion cuyo código habla con `application "Reminders"` y con nada más. Fuera quedan otras apps, `application id`, `do shell script`, `run script`, `open location`, ficheros, portapapeles, comentarios, `«»` y `¬`. Los textos entre comillas son datos y no cuentan, así que un recordatorio puede decir «chrome».
- `ci/test_reminders_hermes.py` (hermético) con su paso en `ci.yml`, `HELPER_UNIDADES` en `install.sh` y una sección en `ARCHITECTURE.md`.

## Efecto observable

Ya está en las máquinas (INFRA-804, `nota-it-informe.md`). Con la clave de las secretarias, desde el pod `hermes-gateway`:

- `reminders <b64>` crea un recordatorio en una lista de prueba, `reminders` con el guion por stdin lo lee y otro guion lo borra con la lista. Los tres salen con rc 0.
- `curl -s localhost:9222/json`, `ssh mac 'curl …:9222'`, `osascript … "Google Chrome"` y `ssh mac uname` los rechaza el puente con rc 2. Un guion de Chrome o un `do shell script` colado por `reminders` lo rechaza el Mac, también con rc 2. La pty y el salto `-W` al sshd del Mac también se rechazan.
- `ssh mac uname` con `nvidiadgx` desde el x86 y la clave del pod con shell en el x86 siguen funcionando igual.

## Lo que esta PR no cierra

El terminal de una secretaria todavía puede leer la clave compartida del pod (`/opt/data/ssh/id_ed25519`), porque todos los perfiles corren con el mismo usuario y en el mismo contenedor. Esa clave entra además al Mac directamente desde el pod. Eso se arregla en el chart de `k8s-openclaw-qwen36-pocharlies` y lo decide security; va en el ticket.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

