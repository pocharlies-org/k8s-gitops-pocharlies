# Legacy Decommission: skirmshop-brain v1

Date: 2026-05-22

> Update 2026-05-28: the `skirmshop-brain-stg` environment was later decommissioned —
> only `prod` remains. The staging references below reflect the state on 2026-05-22 and
> are kept for historical accuracy.

## Summary

The Docker legacy container `skirmshop-brain` on `sauvage` was stopped. It was the v1 runtime using image `skirmshop-brain-brain` and exposing port `5000`.

The official runtime is now Kubernetes v2:

- ArgoCD Application `skirmshop-brain-prod`: `Synced` / `Healthy`
- ArgoCD Application `skirmshop-brain-stg`: `Synced` / `Healthy`
- Prod image: `ghcr.io/pocharlies-org/skirmshop-brain-v2:prod`
- Staging image: `ghcr.io/pocharlies-org/skirmshop-brain-v2:stg`
- Prod health: `https://brain-k8s.lan.e-dani.com/health` -> `200`
- Staging health: `https://brain-stg.lan.e-dani.com/health` -> `200`

No Docker container, image, or volume was removed.

## Backup

Backup directory on `sauvage`:

```bash
/home/ubuntu/backups/k8s-legacy-decom/20260522-skirmshop-brain-v1/
```

Captured files:

- `docker-inspect-skirmshop-brain.json`
- `docker-logs-tail500-skirmshop-brain.log`
- `docker-compose-config.yml`
- `docker-compose-config.stderr`
- `git-origin.txt`
- `git-head.txt`
- `brain-mcp.js.before`
- `openclaw.json.before`
- `SHA256SUMS`

The backup files are not copied into Git because they may contain environment values and runtime details.

## Consumer Audit

Searched local GitOps repos under `/home/dibanez/k8s` for:

- `sauvage:5000`
- `100.109.183.9:5000`
- `127.0.0.1:5000`
- `skirmshop-brain:5000`
- `brain-v1`

Result: no references found in `/home/dibanez/k8s`.

Searched `sauvage:/home/ubuntu/skirmshop` excluding noisy generated/session/cache directories. Matches were historical docs, README files, the legacy v1 repo itself, monitoring notes about the retired v1 service, and old plans. No active Docker container config referenced the legacy endpoint.

Additional live-consumer finding:

- `/home/ubuntu/mcp-servers/dgx-helpers/brain-mcp.js` had fallback `http://127.0.0.1:5000`.
- `/home/ubuntu/.openclaw/openclaw.json` had active Brain URLs pointing to `http://sauvage.taile0ad27.ts.net:5001`.

Both were moved to the Kubernetes v2 LAN endpoint before stopping Docker v1:

```text
https://brain-k8s.lan.e-dani.com
```

`openclaw-gateway.service` was restarted after the config update and remained active.

## Commands Executed

```bash
ssh sauvage 'docker stop skirmshop-brain'
```

No `docker rm`, image deletion, or volume deletion was executed.

## Validation

Post-stop validation:

- `docker ps` no longer shows `skirmshop-brain`.
- `docker ps -a` shows `skirmshop-brain` as `Exited (137)`.
- `http://127.0.0.1:5000/health` on `sauvage` no longer connects.
- `https://brain-k8s.lan.e-dani.com/health` returns `200`.
- `https://brain-stg.lan.e-dani.com/health` returns `200`.
- `skirmshop-brain-prod` remains `Synced` / `Healthy`.
- `skirmshop-brain-stg` remains `Synced` / `Healthy`.
- `kubectl get pods -A` showed no pods in `CrashLoopBackOff`, `Pending`, `ImagePullBackOff`, `ErrImagePull`, `Error`, `CreateContainerConfigError`, or `RunContainerError`.

## Rollback

If a hidden consumer still depends on v1:

```bash
ssh sauvage 'docker start skirmshop-brain'
```

Then validate:

```bash
ssh sauvage 'curl -fsS http://127.0.0.1:5000/health'
```

The container and its data are retained stopped for at least 30 days.
