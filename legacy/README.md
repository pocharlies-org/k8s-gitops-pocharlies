# Transitional Applications

These Applications are still part of the live cutover surface and are kept here
so the new `root` Application is the owner of all currently active ArgoCD
Applications.

- `cnpg-operator` is a Helm chart source and remains required before any CNPG
  `Cluster` resources reconcile.
- `postgres-shared` still points to the legacy `dgx-infra` repository until the
  `databases/postgres-shared` manifests are fully moved into the split repo
  layout. Do not delete it during the first cutover.

