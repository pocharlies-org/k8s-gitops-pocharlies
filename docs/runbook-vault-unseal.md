# Runbook: Unseal Vault after restart

**When to use**: Vault pod restarted (cluster restart, node failure, OOM), showing `sealed=true`.  
**Time**: ~2 minutes.

---

## Detect sealed state

```bash
kubectl -n vault exec vault-0 -- vault status
# Look for: Sealed  true
```

Or via metrics/alerting: alert `VaultSealed` should fire.

---

## Get unseal keys

Open 1Password → search `k3s • Vault Unseal Keys (CRITICAL)`.

You need **3 of the 5 keys** to unseal (Shamir threshold).

---

## Unseal

```bash
# Run 3 times with 3 different keys
kubectl -n vault exec -it vault-0 -- vault operator unseal <KEY_1>
kubectl -n vault exec -it vault-0 -- vault operator unseal <KEY_2>
kubectl -n vault exec -it vault-0 -- vault operator unseal <KEY_3>
```

After the 3rd key:
```
Sealed          false
```

---

## Verify ESO reconnected

External Secrets Operator should auto-reconnect within ~60 seconds:

```bash
kubectl get clustersecretstore vault -o jsonpath='{.status.conditions[0].message}'
# → "Valid"

kubectl get externalsecrets -A
# All should show READY=True
```

---

## Auto-unseal (future)

For production, consider Vault auto-unseal with:
- AWS KMS (if cloud budget allows)
- Transit key from a second Vault instance
- TPM on x86 node

Until then, manual unseal is required after every Vault pod restart. 
The alert `VaultSealed` in AlertManager will page you within 5 minutes.
