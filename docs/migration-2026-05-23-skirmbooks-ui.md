# Migration: skirmbooks-ui

Date: 2026-05-23

## Runtime

`skirmbooks-ui` was moved from Sauvage Docker to k8s.

- Namespace: `skirmshop`
- Deployment: `skirmbooks-ui`
- Service: `skirmbooks-ui:80`
- Image: `harbor.e-dani.com/homelab/skirmbooks-ui:k8s-20260523-legacy`
- Public host: `skirmbooks.e-dani.com`
- Health endpoint: `/api/health`

The GitOps repo is prepared locally at:

```text
/home/dibanez/k8s/k8s-skirmbooks-pocharlies
```

GitHub repo creation is pending because the GitHub API core rate limit was exhausted during the migration. Until that repo is created and added to the root app, the k8s Deployment/Service were applied manually from the prepared repo.

## Database

Source legacy DB:

```text
Docker shared-postgres / database gestoria
```

Target definitive DB:

```text
postgres-shared-rw.databases.svc.cluster.local / database skirmbooks
```

Restore notes:

- Dumped `gestoria` with `pg_dump -Fc`.
- Restored into `skirmbooks` with `pg_restore --clean --if-exists --no-owner --no-acl`.
- Granted access on `gestoria_*` schemas/tables/sequences to role `skirmshop`.
- Connection string uses `options=-c app.tenant_id=skirmshop` because the restored tables enforce RLS through `current_setting('app.tenant_id')`.

Validation:

- Base table row-count diff: `0`
- k8s `/api/health` counts:
  - `banking_movements`: `10`
  - `invoices_in`: `6`
  - `entries`: `7`
  - `modelos`: `1`

## Backups

Sauvage backup directory:

```text
/home/ubuntu/backups/k8s-legacy-decom/20260523-skirmbooks-ui
```

Contents include:

- `gestoria.source.shared-postgres.dump`
- `gestoria.source.base-rowcounts.tsv`
- `skirmbooks.target.base-rowcounts.tsv`
- `base-rowcounts.diff`
- `skirmbooks-ui.inspect.before-stop.json`
- `skirmbooks-ui.tail500.before-stop.log`
- `docker-compose.config.before-stop.yml`
- `docker-compose.yml`
- `Dockerfile`
- `package.json`

## Cutover

Traefik Edge route `edge-other-legacy-proxies` now sends:

```yaml
Host(`skirmbooks.e-dani.com`) -> skirmbooks-ui.skirmshop.svc.cluster.local:80
```

Post-cutover checks:

- `https://skirmbooks.e-dani.com/` -> `302` to `/dashboard`
- `https://skirmbooks.e-dani.com/api/health` -> `200`
- Docker `skirmbooks-ui` -> `Exited (0)`

## Rollback

```bash
ssh sauvage 'cd /home/ubuntu/skirmshop/skirmshop-gestoria/skirmbooks-ui && docker compose up -d app'
```

Then point `edge-other-legacy-proxies` back to:

```yaml
services:
  - name: sauvage-localhost
    port: 3050
```

and resync `k8s-infra`.
