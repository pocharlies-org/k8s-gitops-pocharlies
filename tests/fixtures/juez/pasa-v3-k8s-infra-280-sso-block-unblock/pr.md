INFRA-832: SSO en los POST block/unblock de background-consumers

## Alcance de esta PR

- C1: el diff solo añade `PathRegexp(^/api/litellm/background-consumers/[^/]+/(block|unblock)$)` a las reglas POST con sso-chain de `dgx-public-host-lan.yaml` y `dgx-dashboard-public.yaml`; nada más cambia.

## Qué cambia

DGX-812 publicó `POST /api/litellm/background-consumers/{alias}/block|unblock` en el dashboard DGX (bloquea las keys de LiteLLM de aurora, keep y k8sgpt). En LAN/tailnet esa escritura llegaba al backend sin SSO porque el router POST de `sso-chain` solo lista `/api/cluster/apply`, scale/restart, argocd sync/rollback y `/api/compute/mode`. Se añade la ruta al mismo OR, con el mismo `&& Method(`POST`)`:

- `networking/traefik-lan/dgx-public-host-lan.yaml`: 2 reglas (`dgx.e-dani.com` + `dgx.lan.e-dani.com`, y `s3.e-dani.com`).
- `networking/traefik-edge/dgx-dashboard-public.yaml`: 1 regla (`dgx.e-dani.com`).

El GET (`/api/litellm/background-consumers`) y el resto de `/api/litellm` siguen abiertos. 3 líneas cambiadas, ninguna otra.

## Verificación (antes del cambio y sobre la rama)

- Antes: `curl -s -o /dev/null -w '%{http_code}' -X POST https://dgx.lan.e-dani.com/api/litellm/background-consumers/qa-probe/block` -> `404` (llega al backend sin SSO), el test que debe fallar.
- PyYAML: los dos ficheros parsean; las 3 reglas con el regexp nuevo llevan `sso-chain` y `Method(POST)`.
- `kubectl kustomize .` -> OK. `kubectl apply --dry-run=client` de los dos ficheros -> OK (no se aplicó nada al clúster).
- `python3 -m unittest discover -s tests`: 467 casos, 1 fallo (`test_traefik_lan_ks5_ha_contract::test_harbor_lan_resolves_to_the_cluster_service`), que falla igual en `origin/main` sin este cambio (comentario de CoreDNS con `192.168.50.240`), ajeno a esta PR.

Ticket: INFRA-832. Relacionada: DGX-812.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

