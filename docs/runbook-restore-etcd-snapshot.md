# Runbook: Restore k3s cluster from etcd snapshot

**When to use**: cluster is unresponsive, etcd data corrupted, or accidental mass-delete.  
**RTO**: ~15 minutes from snapshot restore to cluster Ready.  
**Last tested**: _(update when exercised)_

---

## Pre-conditions

- You have SSH access to the x86 master node.
- You know which snapshot to restore from (see step 1).
- Cluster is stopped or degraded (you can also restore to a fresh node).

---

## Step 1 — Identify the snapshot

### From local storage (on x86)
```bash
ls -lh /var/lib/rancher/k3s/server/db/snapshots/
# → etcd-snapshot-<timestamp>
```

### From MinIO S3 (off-site)
```bash
# On x86 or workstation with mc configured
mc ls minio/k3s-etcd-snapshots/x86-master/
# Download the snapshot you want to restore
mc cp minio/k3s-etcd-snapshots/x86-master/<snapshot-name> /tmp/etcd-restore.db
```

---

## Step 2 — Stop k3s on all nodes

```bash
# On x86 (master)
ssh x86 sudo systemctl stop k3s

# On all workers (not strictly required but avoids confusion)
ssh dgx1 sudo systemctl stop k3s-agent
ssh dgx2 sudo systemctl stop k3s-agent
ssh sauvage sudo systemctl stop k3s-agent
```

---

## Step 3 — Restore the snapshot

```bash
# On x86 — replace <snapshot-file> with the filename (or full path if from S3)
ssh x86 sudo k3s server \
  --cluster-reset \
  --cluster-reset-restore-path=/var/lib/rancher/k3s/server/db/snapshots/<snapshot-file>

# If snapshot was downloaded from S3 to /tmp:
ssh x86 sudo k3s server \
  --cluster-reset \
  --cluster-reset-restore-path=/tmp/etcd-restore.db
```

k3s will print a message like:
```
Managed etcd cluster membership has been reset, restart without --cluster-reset flag now.
```
Then it exits. This is expected.

---

## Step 4 — Start k3s normally

```bash
ssh x86 sudo systemctl start k3s

# Watch until master is Ready
ssh x86 kubectl get nodes --watch
```

---

## Step 5 — Re-join workers

Workers will reconnect automatically once the master is back. If they don't reconnect within 5 minutes:

```bash
# On each worker
ssh dgx1 sudo systemctl restart k3s-agent
ssh dgx2 sudo systemctl restart k3s-agent
ssh sauvage sudo systemctl restart k3s-agent
```

---

## Step 6 — Verify

```bash
kubectl get nodes
# → 4 nodes Ready

kubectl get pods -A | grep -v Running | grep -v Completed
# → should be empty after ~5 min

# Check ArgoCD synced
kubectl get applications -n argocd
```

---

## Rollback (if restore made things worse)

```bash
# Restore a different snapshot or reset to empty
ssh x86 sudo k3s server --cluster-reset
# WARNING: this destroys all etcd data. Last resort only.
```

---

## Notes

- k3s snapshots are self-contained: they include all cluster state (secrets, deployments, PVCs metadata).
- **PVC data** (Longhorn volumes, NFS data) is NOT in the etcd snapshot — it's on the storage nodes and survives independently.
- After restore, Longhorn may show degraded replicas. This is normal; let Longhorn reconcile (5–15 min).
- Vault pods will start sealed after a cluster restore — unseal manually using 1Password keys.
