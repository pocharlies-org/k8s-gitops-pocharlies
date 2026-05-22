# Legacy Decommission: affiliate-api

Date: 2026-05-23

## Scope

Moved public affiliate traffic off the Sauvage Docker container `affiliate-api` and onto the k8s runtime managed by ArgoCD:

- ArgoCD app: `shopify-affiliate`
- Namespace: `skirmshop`
- Deployment: `affiliate-app`
- Service: `affiliate-app:80`
- Public hosts: `affiliate.skirmshop.es`, `go.skirmshop.es`

## GitOps Changes

- Created/published `pocharlies-org/k8s-shopify-affiliate-pocharlies`.
- Added `shopify-affiliate` to the root GitOps app.
- Updated Traefik Edge route `edge-affiliate-legacy` so both affiliate hosts target:

```yaml
services:
  - name: affiliate-app
    namespace: skirmshop
    port: 80
```

## Backups

Sauvage backup directory:

```text
/home/ubuntu/backups/k8s-legacy-decom/20260523-affiliate-api
```

Contents:

- `affiliate-api.inspect.before-stop.json`
- `affiliate-api.tail500.before-stop.log`
- `docker-compose.config.before-stop.yml`
- `docker-compose.yml`
- `.env`
- `package.json`
- `affiliate.postgres-shared.dump`
- `affiliate.rowcounts.tsv`
- `SHA256SUMS`

The `pg_dump` was taken from the definitive shared PostgreSQL cluster:

```text
postgres-shared-rw.databases.svc.cluster.local / database affiliate
```

`sha256sum -c SHA256SUMS` passed on Sauvage.

## Validation

Before cutover, Docker and k8s returned equivalent responses:

- Docker `http://127.0.0.1:3462/health` -> `200`
- k8s `http://affiliate-app.skirmshop.svc.cluster.local/health` -> `200`
- `/` -> `302` to `/portal/login`
- `/portal/login` -> `200`

After cutover:

- `affiliate.skirmshop.es /health` -> `200`
- `affiliate.skirmshop.es /` -> `302`
- `affiliate.skirmshop.es /portal/login` -> `200`
- `go.skirmshop.es /health` -> `200`
- `go.skirmshop.es /` -> `302`
- `go.skirmshop.es /portal/login` -> `200`
- `http://127.0.0.1:3462/health` -> connection refused
- ArgoCD `shopify-affiliate` -> `Synced/Healthy`
- ArgoCD `k8s-infra` -> `Synced/Healthy`

## Docker State Note

`docker stop affiliate-api` and `docker kill affiliate-api` timed out after the route was moved. The legacy port is closed, `ss` shows no listener on `:3462`, and `ctr -n moby tasks ls` shows no task for the Docker container ID. However, `docker ps` still reports `affiliate-api Up`.

Docker live-restore is disabled on Sauvage, so Docker daemon restart was intentionally deferred because it could disrupt remaining legacy stateful containers (`libreplay-*`, `shared-postgres`, `shared-rabbitmq`, `skirmbooks-ui`). Treat `affiliate-api` as decommissioned from traffic, with Docker metadata cleanup deferred until the remaining Docker stateful workloads are migrated or a maintenance window is available.

## Rollback

Preferred rollback while Docker metadata is stale:

```bash
cd /home/ubuntu/skirmshop/shopify-affiliate-api
docker compose up -d app
```

Then temporarily point `edge-affiliate-legacy` back to:

```yaml
services:
  - name: sauvage-localhost
    port: 3462
```

and resync `k8s-infra`.
