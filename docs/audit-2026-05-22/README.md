# k8s GitOps Cutover Audit - 2026-05-22

This directory captures the live cluster state immediately before cutting
ArgoCD root from the legacy `pocharlies/k3s-gitops` repository to
`pocharlies/k8s-gitops-pocharlies`.

## Source Snapshot

- Existing root Application: `git@github.com:pocharlies/k3s-gitops.git`, path `apps`
- New root target: `https://github.com/pocharlies/k8s-gitops-pocharlies`, path `.`
- Shared PostgreSQL target: `databases/postgres-shared`
- n8n database mode: PostgreSQL, not SQLite

## Exported Live Manifests

- `live-yaml/application-root.yaml`
- `live-yaml/application-n8n.yaml`
- `live-yaml/application-postgres-shared.yaml`
- `live-yaml/application-cnpg-operator.yaml`
- `live-yaml/n8n-stack.yaml`
- `live-yaml/cnpg-clusters.yaml`
- `live-yaml/ingressroutes.yaml`
- `live-yaml/externalsecrets.yaml`
- `live-yaml/pvcs.yaml`
- `live-yaml/databases-shared-postgres.yaml`
- `live-yaml/skirmshop-stateful-and-apps.yaml`

These files are rollback/audit evidence only. Do not treat them as the new
source of truth; the source of truth after cutover is the set of
`k8s-*-pocharlies` repositories.

Known literal secret-like values in generated deployment exports were redacted
before committing.
