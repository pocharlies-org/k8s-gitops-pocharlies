# Runbook: Evacuate a worker node (maintenance / failure)

**When to use**: planned maintenance, node hardware failure, k3s agent upgrade.  
**Impact**: pods on the node are rescheduled to other nodes. StatefulSets may have brief downtime.

---

## Step 1 — Cordon the node (stop new scheduling)

```bash
kubectl cordon <node-name>
# Example: kubectl cordon dgx2
```

---

## Step 2 — Drain the node

```bash
kubectl drain <node-name> \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --grace-period=30 \
  --timeout=300s
```

Flags:
- `--ignore-daemonsets`: skip DaemonSet pods (Alloy, GPU device plugin) — they'll restart automatically.
- `--delete-emptydir-data`: removes ephemeral pods with emptyDir volumes.
- For StatefulSets with PDBs, drain may stall — override with `--force` only if you accept the risk.

### Special case: sauvage

Sauvage has `role=edge:NoSchedule` taint. Before draining, check if any ingress traffic is affected:

```bash
kubectl get pods -n traefik-edge --field-selector spec.nodeName=sauvage
# If Traefik EDGE is running, public ingress will be down during drain
# Option: use Cloudflare Tunnel as fallback before draining
```

---

## Step 3 — Perform maintenance

For hardware maintenance, power off the node safely:
```bash
ssh <node> sudo shutdown -h now
```

For k3s agent upgrade:
```bash
ssh <node> "curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=<target-version> sh -s - agent"
```

---

## Step 4 — Restore the node

```bash
# Start k3s agent (or power on node)
ssh <node> sudo systemctl start k3s-agent

# Wait for Ready
kubectl get nodes --watch | grep <node-name>
```

---

## Step 5 — Uncordon

```bash
kubectl uncordon <node-name>
```

Pods won't automatically move back (Kubernetes doesn't rebalance). They'll stay on their current nodes unless you force it:

```bash
# Optional: restart deployments to rebalance
kubectl rollout restart deployment -n <namespace>
```

---

## Step 6 — Longhorn rebalance

After a node returns, Longhorn may try to rebuild replicas. Watch:

```bash
kubectl -n longhorn-system get volumes
# Degraded volumes will show rebuilding status — allow up to 30 min
```

If Longhorn replica rebuild is stuck:
```bash
kubectl -n longhorn-system get replicas | grep Error
kubectl -n longhorn-system describe replica <replica-name>
```
