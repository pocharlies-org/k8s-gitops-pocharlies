# Runbook: Restore namespace from Velero backup

**When to use**: namespace deleted, corrupted app state, post-incident recovery.  
**RTO**: ~5–30 minutes depending on PVC size.  
**Last tested**: _(update when exercised)_

---

## Pre-conditions

- Velero CLI installed on workstation (`brew install velero` or from releases).
- `kubectl` context pointing at the cluster.
- MinIO/S3 backend accessible (`s3.lan.e-dani.com`).

---

## Step 1 — List available backups

```bash
velero backup get
# OR
kubectl get backups -n velero
```

Output shows backup name, status, expiry. Names follow the schedule:
- `daily-critical-<timestamp>` — daily at 03:00 UTC
- `weekly-all-<timestamp>` — Sundays 05:00 UTC

---

## Step 2 — Inspect backup contents

```bash
velero backup describe <backup-name> --details
# Shows: namespaces included, PVCs snapshotted, resource counts
```

---

## Step 3 — Restore to a new namespace (safe/test)

```bash
velero restore create --from-backup <backup-name> \
  --namespace-mappings <original-ns>:<new-ns> \
  --wait

# Example: restore vault to vault-restore for inspection
velero restore create --from-backup daily-critical-20260520-030000 \
  --namespace-mappings vault:vault-restore \
  --wait
```

---

## Step 4 — Restore in-place (overwrite existing)

```bash
# First delete the broken namespace if it exists
kubectl delete namespace <namespace> --wait=true

# Then restore
velero restore create --from-backup <backup-name> \
  --include-namespaces <namespace> \
  --wait
```

---

## Step 5 — Monitor restore progress

```bash
velero restore get
kubectl get restore -n velero <restore-name> -o yaml
# Look for: phase: Completed (or PartiallyFailed with warnings)
```

---

## Step 6 — Verify

```bash
kubectl get pods -n <namespace>
kubectl get pvc -n <namespace>

# For databases: check row counts, application smoke test
```

---

## Common issues

| Issue | Fix |
|---|---|
| PVC stuck in Pending | Longhorn CSI snapshots may need manual trigger: `kubectl describe volumesnapshot` |
| Restore PartiallyFailed | Check `velero restore describe --details`; usually harmless CRD warnings |
| Vault starts sealed | Expected — unseal with 3/5 keys from 1Password (`k3s • Vault Unseal Keys`) |
| ArgoCD shows OutOfSync after restore | Expected — ArgoCD will re-sync from Git. Let it reconcile before manually editing |
