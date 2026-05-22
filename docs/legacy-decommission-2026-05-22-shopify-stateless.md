# Legacy Decommission - Shopify Stateless Apps

Date: 2026-05-22

## Scope

Stopped Docker legacy containers on `sauvage` after validating that public
routes are served by k8s/Traefik:

- `bundles-app`
- `skirmshop-picker`
- `sii-app`

No containers, images, volumes, bind mounts, or compose directories were
deleted.

## Backup

Backup directory:

`/home/ubuntu/backups/k8s-legacy-decom/20260522-shopify-stateless/`

Captured:

- `docker inspect` for each stopped container
- last 500 Docker log lines for each stopped container
- `docker compose config` for each compose project
- `/var/lib/skirmshop-picker` tarball
- `shared-postgres` Docker `pg_dumpall` before stop:
  `shared-postgres-pgdumpall-before-stop.20260522T112743Z.sql.gz`

## Runtime After Decommission

Official runtimes are k8s/GitOps:

- `shopify-bundles` -> `k8s-shopify-bundles-pocharlies`
- `shopify-picker` -> `k8s-shopify-picker-pocharlies`
- `shopify-sii` -> `k8s-shopify-sii-pocharlies`

Validated ArgoCD status after stop:

- `shopify-bundles`: `Synced/Healthy`
- `shopify-picker`: `Synced/Healthy`
- `shopify-sii`: `Synced/Healthy`

Validated k8s Deployments after stop:

- `bundles-app`: `1/1`
- `skirmshop-picker`: `1/1`
- `sii-app`: `1/1`

Public route smoke checks against `https://skirmshop.e-dani.com` returned
application-level responses from k8s:

- `/picker`: `400 Missing shop parameter`
- `/picker/shopify/purchase-orders`: `400 Missing shop parameter`
- `/bundles`: `410`
- `/bundles/`: `410`
- `/sii`: `410`
- `/sii/`: `410`

## Rollback

If a hidden consumer still depends on Docker legacy:

```bash
ssh sauvage 'docker start bundles-app skirmshop-picker sii-app'
```

Then recheck the affected route and inspect the consumer before attempting
decommission again.
