# Skirmshop Project Registry

Last observed: 2026-05-25 on `sauvage:/home/ubuntu/skirmshop`.

This registry is the handoff point for moving every Skirmshop runtime to k8s
without losing half-finished projects. The machine-readable source is
`skirmshop-project-registry.yaml`.

## Current policy

- Active runtime is canonical in k8s/GitOps.
- Inactive projects get disabled k8s skeletons first: no public ingress,
  `replicas: 0`, and CronJobs with `suspend: true`.
- Activation order is dependencies first: host crons and shared infra before
  optional product apps.
- Legacy host crons and routes are removed only after a validated k8s
  equivalent exists.

## Active in k8s

- `shopify-affiliate`, with host crons still pending validation/cutover.
- `shopify-bundles`.
- `shopify-chatbot`, with monitoring/reporting crons still on host.
- `shopify-collections-tree`.
- `shopify-label`.
- `shopify-picker`.
- `shopify-serial-numbers`.
- `shopify-sii`.
- `shopify-translations`.
- `skirmbooks`.
- `skirmshop-brain-prod` (single environment; `skirmshop-brain-stg` decommissioned 2026-05-28).
- `firecrawl`.

## Active outside k8s

- `shopify-sync-app`: host cron `warehouse_sync` every 4 hours at minute 17.
- `skirmshop-monitoring`: backup, chatbot sync/report, Gmail metrics, and cron wrapper scripts.
- `skirmshop-brain-v2/scripts/run_full_audit.sh`: host cron daily at 04:30.
- `shopify-affiliate-api`: host `gdpr-prune` and `sync-discounts` crons remain while k8s CronJobs are suspended.
- `shared-infra`: `shared-postgres` and `shared-rabbitmq` still run in Docker on `sauvage`.
- `pocharlies-redis`: host Docker Redis dependency still running.

## Disabled skeletons created

- `k8s-shopify-sync-pocharlies`: CronJob-only skeleton with PVC state, suspended.
- `k8s-shopify-back-in-stock-pocharlies`: Shopify app skeleton, `replicas: 0`, no ingress.
- `k8s-shopify-product-ai-pocharlies`: Shopify app skeleton, `replicas: 0`, no ingress.
- `k8s-skirmshopshopifyapp-pocharlies`: legacy Shopify app skeleton, `replicas: 0`, no ingress.
- `k8s-pocharlies-webgui-pocharlies`: Open WebUI skeleton, `replicas: 0`, no ingress.
- `k8s-skirmshop-competitor-crawler-pocharlies`: crawler skeleton, `replicas: 0`, no ingress.

## Activation checklist

1. Confirm the source repo and production branch.
2. Add or verify the Vault secret path listed in the YAML registry.
3. Build and push the image referenced by the skeleton, replacing the `pending` tag.
4. Run `kustomize build k8s` and kubeconform for the skeleton repo.
5. Add the matching Application from `apps-disabled/` to the root GitOps kustomization only when ready.
6. Keep replicas at 0 or CronJobs suspended until a manual validation Job succeeds.
7. Move traffic or remove the host cron only after k8s logs, metrics, and rollback are validated.

## Known gotchas

- Do not unsuspend affiliate CronJobs until the released image is verified to
  include the TS scripts it runs.
- `shopify-sync-app` currently writes `.warehouse-sync-state.json` beside its
  source script. The skeleton uses a PVC-backed symlink in the command so state
  can survive pod replacement.
- Legacy routes to host ports `3100`, `3456`, `3459`, and `3470` are treated as
  cleanup candidates, not as evidence of live apps.
