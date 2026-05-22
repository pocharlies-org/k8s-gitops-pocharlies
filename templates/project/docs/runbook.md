# PROJECT Runbook

## Environments

- Staging: `PROJECT-stg`, branch `stg`, overlay `k8s/overlays/stg`
- Production: `PROJECT`, branch `main`, overlay `k8s/overlays/prod`

## Release Flow

1. Develop on a feature branch.
2. Open a PR into `stg`.
3. Merge to `stg`; CI builds `stg-<sha>`, stamps the staging overlay, and ArgoCD deploys staging.
4. Smoke test staging.
5. Open PR `stg` -> `main`.
6. Tag the release commit; release workflow builds and pushes immutable images to Harbor.
7. Update the production image tag/digest when ready, then let ArgoCD deploy production.

## Secrets

Secrets live in Vault and are consumed through ExternalSecrets:

- `secret/PROJECT/stg/...`
- `secret/PROJECT/prod/...`

No secret values belong in GitHub Actions logs, manifests, or docs.

## Database

- Staging DB: `PROJECT_stg`, owner `PROJECT_stg`
- Production DB: `PROJECT`, owner `PROJECT`

Run migrations as explicit Jobs or explicit pipeline steps. Record the command,
image tag, and result in this runbook when a manual migration is needed.

## Rollback

Preferred rollback:

1. Revert the production overlay image stamp or restore the previous `vX.Y.Z`.
2. Merge to `main`.
3. Confirm ArgoCD sync and smoke test.

Emergency rollback:

1. Use ArgoCD to sync the previous known-good revision.
2. Record the reason here.
3. Follow with a Git revert so declared state matches the cluster.

## kubectl

Allowed in dev/stg for debugging: logs, describe, exec, port-forward, temporary
image/env experiments.

Production mutation is emergency-only. Record any command here with timestamp,
operator, reason, and Git follow-up.
