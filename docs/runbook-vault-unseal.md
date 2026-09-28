# Runbook: Unseal Vault — RETIRADO (2026-09-28)

**Vault ya no existe en este clúster.** Se retiró el 2026-09-28 tras completar
SC-699: los ~240 ExternalSecret migraron al `ClusterSecretStore/onepassword`
(1Password, vault `k8s-pocharlies`, service account `k3s-external-secrets`) y la
Application `vault` se borró con `--cascade` bajo decisión expresa del operador
(snapshot raft final: `~/backups/vault-raft-final-2026-09-28.snap`, sha256
`11f08d675ba9177a594a96aa7448ff513ab7422a4da898e540c81cf39a2f2fbb`).

No hay nada que desellar. Si un restaurado de clúster (velero/etcd) levantara
algún residuo del namespace `vault`, es basura: bórralo y usa 1Password.

- Fuente de verdad de secretos: 1Password → `ClusterSecretStore/onepassword`.
- Evidencia del cierre: `~/k8s/_ops/vault-to-1password/fase6-evidencia/` y el
  histórico de [SC-699](https://e-dani.atlassian.net/browse/SC-699).
- El runbook anterior está en el historial de git de este fichero.
