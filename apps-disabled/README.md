# Disabled Skirmshop Applications

These Application manifests are intentionally not referenced by the root
`kustomization.yaml`.

Use them when a half-finished Skirmshop project is ready for staged k8s
activation. Every referenced repo must stay disabled by default: no public
IngressRoute, Deployments at `replicas: 0`, and CronJobs with `suspend: true`.

Activation rule:

1. Validate the source image and Vault secret.
2. Render and validate the skeleton repo.
3. Add the Application to the root kustomization.
4. Sync with no running workload or suspended CronJob.
5. Run a manual validation Job or scale a private Deployment.
6. Only then remove the matching host cron or legacy route.
