# CI/CD + GitOps Standard

This is the project contract for services deployed to the k3s cluster.

## Repository Shape

Every application repository should converge to this shape:

```text
repo/
  app/
  Dockerfile
  .github/workflows/
    ci.yml
    deploy-stg.yml
    release.yml
  k8s/
    base/
      deployment.yaml
      service.yaml
      ingress.yaml
      externalsecret.yaml
      kustomization.yaml
    overlays/
      stg/
        kustomization.yaml
        patch-env.yaml
        patch-image.yaml
      prod/
        kustomization.yaml
        patch-env.yaml
        patch-image.yaml
  docs/
    runbook.md
```

Multi-service repositories may keep several Dockerfiles and several Deployment
resources, but the same rule holds: `k8s/base` is shared, environment differences
live only in overlays, and ArgoCD owns stable state.

## Branch and Environment Model

- any branch push: CI lint/test/manifest validation.
- `stg`: build immutable `stg-<sha>` images, stamp `k8s/overlays/stg`, ArgoCD deploys staging.
- PR `stg` -> `main`: review the already-tested staging changes.
- any Git tag: build release images, fail closed on fixable HIGH/CRITICAL
  vulnerabilities or embedded secrets, and only then push them to Harbor.
- production deploys: the release workflow creates a promotion branch from the
  latest ArgoCD-tracked branch and opens a PR with the immutable artifact digest.

Tags must be Docker-compatible image tags (`v1.2.3`, `2026.05.22`, etc.).
The release workflow also publishes `sha-<short_sha>` for traceability.
Every published digest is signed keylessly with the GitHub Actions OIDC
identity, receives a signed SPDX JSON SBOM attestation, and is verified before
the workflow succeeds. The workflow uploads a 90-day evidence artifact with
the digest and SBOM. Callers of `reusable-release.yml` must grant only:

```yaml
permissions:
  contents: read
  id-token: write
```

The OIDC permission is used exclusively for Sigstore signing; no long-lived
Cosign key or password is accepted. A failed scan may leave no published tag;
a signing or attestation failure leaves an unsigned digest that must never be
promoted. Production manifests pin the verified `repository@sha256:...`, not
either mutable tag.

It must not push directly or force-push to `deploy/prod`. The promotion PR must
pass required checks and review; this shared workflow never auto-merges it.

## Environment Rules

Staging and production must be as similar as practical. Allowed differences:

- namespace
- hostname
- replicas and resources when justified
- database name/user
- Vault paths
- external endpoints

Never commit secrets. Use Vault through ExternalSecrets:

- `secret/<project>/stg/...`
- `secret/<project>/prod/...`

Each environment gets its own database and user:

- staging: `<project>_stg`, owner `<project>_stg`
- production: `<project>`, owner `<project>`

Migrations must run as an explicit Kubernetes Job or an explicit pipeline step.
Do not hide migrations inside application startup unless the runbook says why.

## ArgoCD Contract

Each project gets two Applications:

- `<project>-stg`: `targetRevision: stg`, `path: k8s/overlays/stg`
- `<project>`: `targetRevision: deploy/prod`, `path: k8s/overlays/prod`

Use:

- `selfHeal: true`
- `prune: false` until the project has completed at least one clean rollback drill
- sync waves for ExternalSecrets, DB/bootstrap Jobs, migration Jobs, then Deployments

Do not enable the staging Application in the root Kustomization until the remote
`stg` branch exists and the staging Vault paths have been created. The
`apps/socialmedia-stg.yaml` file is intentionally present as the first concrete
example but is not wired into `kustomization.yaml` yet.

## kubectl Policy

`kubectl` is allowed for temporary investigation and fast feedback in dev/stg:

- `kubectl logs`, `describe`, `exec`, `port-forward`
- temporary image/env changes in staging while debugging
- one-off Jobs in staging to prove a migration or repair

Stable state must go back to Git. If a `kubectl` change survives the debugging
session, create the equivalent commit in the app repo or GitOps repo.

Production `kubectl` mutation is emergency-only. Document it in the project
runbook with time, command, reason, observed impact, and the Git follow-up.

## Rollback

Preferred rollback is Git:

1. Create a rollback branch from the latest `deploy/prod` and revert the
   production overlay commit or restore the previous digest.
2. Open, review and merge a PR into `deploy/prod`.
3. Let ArgoCD reconcile production and verify health/soak.

Emergency rollback may use ArgoCD UI/CLI to sync an older Git revision. Follow
with a Git revert so the declared state matches what is running.

## Required Secrets

Each repository using the reusable workflows needs GitHub Actions secrets:

- `HARBOR_USER`
- `HARBOR_PASSWORD`
- `OPENCLAW_GITHUB_NOTIFY_URL` or `OPENCLAW_IDENTITY_B64`

The default registry for CI/CD pushes is `harbor.lan.e-dani.com/homelab`.

Failure notifications are sent to OpenClaw for the Telegram destination
`synaspte` / `github`. The preferred path is an OpenClaw webhook URL that
accepts the reusable workflow JSON payload. As a fallback, CI can install the
OpenClaw CLI and use these additional secrets:

- `OPENCLAW_GATEWAY_URL`
- `OPENCLAW_TELEGRAM_ACCOUNT`
- `OPENCLAW_TELEGRAM_TARGET`
- `OPENCLAW_TELEGRAM_THREAD_ID`

## Runner Standard

Workflows run on Actions Runner Controller scale sets in `arc-runners`.
Because `pocharlies` is a personal GitHub account, runners are registered
per-repository. Manifest-only repositories use their repo-specific scale-set
(`arc-infra`, `arc-gitops`, etc.); `k8s-socialmedia-pocharlies` keeps the
existing `arc-amd64` scale-set for image builds.

Image-building runners use `containerMode.type: dind`. DinD is privileged and
must stay isolated in the `arc-runners` namespace.
