# Ops Progress - 2026-05-22 - Velero, Firecrawl, TLSStore

## Velero smoke test

- Backup CR: `smoke-20260522130355`
- Backup phase: `Completed`
- Restore CR: `smoke-restore-20260522130355`
- Restore phase: `Completed`
- Restored namespace: `velero-smoke-restore-20260522130355`
- Payload verified: ConfigMap value `velero smoke 20260522130355`
- Cleanup: restore namespace removed after validation

Operational note: `kubectl get backup` is ambiguous in this cluster because
Longhorn also defines a `Backup` resource. Use `backups.velero.io` explicitly.

## Firecrawl

- Argo app: `firecrawl`
- Git revision validated: `153603ad88b031a3da956b463f563d7ea7e9db91`
- Public endpoint: `https://firecrawl.e-dani.com`
- LAN endpoint: `https://firecrawl.lan.e-dani.com`
- k8s service: `firecrawl-api.skirmshop.svc.cluster.local:3002`
- Validation: POST `/v2/scrape` against `https://firecrawl.lan.e-dani.com`
  returned `200` and successfully scraped `https://example.com`.

OpenClaw on `sauvage` was configured to use the LAN endpoint:

- Config path: `/home/ubuntu/.openclaw/openclaw.json`
- Backup path: `/home/ubuntu/backups/k8s-legacy-decom/20260522-firecrawl-openclaw/`
- Plugin status: `firecrawl` enabled and loaded by `openclaw gateway call health`

## TLSStore standard

Traefik LAN and EDGE now have default TLSStores:

- `traefik-lan/default` -> `wildcard-lan-tls`
- `traefik-edge/default` -> `wildcard-public-tls`

Updated active app repos to avoid `tls: {}` in ServerSideApply-managed
IngressRoutes:

- `k8s-firecrawl-pocharlies`
- `k8s-litellm-pocharlies`
- `k8s-libreplay-pocharlies`
- `k8s-teslamate-pocharlies`
- `k8s-shopify-picker-pocharlies`
- `k8s-shopify-label-pocharlies`
- `k8s-shopify-bundles-pocharlies`
- `k8s-shopify-sii-pocharlies`
- `k8s-socialmedia-pocharlies`

All affected ArgoCD Applications were validated as `Synced/Healthy` after sync.
