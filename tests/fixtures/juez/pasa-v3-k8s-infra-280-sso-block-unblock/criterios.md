# INFRA-832 · criterios del 00-spec.md

- [ ] El diff solo añade ese PathRegexp a las reglas POST con sso-chain de los dos ficheros; nada más cambia.
- [ ] Tras el sync de `k8s-infra`: `curl -s -o /dev/null -w '%{http_code}' -X POST https://dgx.lan.e-dani.com/api/litellm/background-consumers/qa-probe/block` → 302 (hoy 404)
