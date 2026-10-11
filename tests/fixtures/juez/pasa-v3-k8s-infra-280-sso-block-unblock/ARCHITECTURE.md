# ARCHITECTURE.md — k8s-infra-pocharlies

> Infraestructura del cluster k3s: networking (Traefik, MetalLB, cert-manager, DNS), plataforma (Harbor, Keycloak,
> Kyverno, CNPG…), Postgres compartido, Ansible/Terraform del plan KS-5 y runbooks. Una de las raíces más
> consumidas del estate. Escrito por `architect` (SC-1426).

## 1. Clientes y versiones

Sin clientes de usuario. Despliega **4 Applications** de ArgoCD (todas desde este repo, tronco **`main`**, sync
automático `prune: false`, `selfHeal: true`):

| Application | fuente | versión | notas |
|---|---|---|---|
| `k8s-infra` | path `.` (kustomize raíz: cert-manager issuers, CoreDNS, metallb ippool, IngressRoutes de `traefik-lan` y `traefik-edge`, networkpolicies…) | `origin/main` = 5d52ca2 | ~49+ recursos listados en `kustomization.yaml` |
| `postgres-shared` | path `databases/postgres-shared` | CNPG | BD compartida (litellm, langfuse, firecrawl, intake…) |
| `traefik-edge` | multi-source: chart `traefik` 40.2.0 (`traefik.github.io/charts`) + values de este repo | 40.2.0 | DaemonSet hostNetwork en sauvage/ks5 |
| `traefik-lan` | ídem, chart `traefik` 40.2.0 | 40.2.0 | LAN `192.168.50.240` |

## 2. Dependencias, en ambos sentidos

- **Depende de** — `k8s-gitops-pocharlies` (registra las Applications y su CI reutilizable `reusable-ci.yml@96ec4d91…`),
  charts upstream, Cloudflare/OVH (DNS y servidores KS-5), Tailscale, Vault/1Password (ExternalSecrets), 1Password
  Connect en el propio clúster (`platform/onepassword-connect`; secretos fuera de banda: `op-credentials` en el ns
  `onepassword-connect` y `onepassword-connect-token` en `external-secrets-operator`; imagen en Harbor).
- **Dependen de él** — prácticamente todo: cada host público/LAN nuevo necesita su IngressRoute aquí
  (`networking/traefik-edge/*-public.yaml`, `networking/traefik-lan/*-lan.yaml`; el DaemonSet del edge solo observa un
  allowlist de namespaces, por eso rutas como `langfuse-public.yaml` viven aquí); `k8s-adguard-pocharlies` (rewrites DNS
  de cada host nuevo); Postgres compartido; `platform/keycloak-next` (`ROLES.yaml`, registro de roles consumido por
  AgentGateway).
- Contratos: `platform/keycloak-next/ROLES.yaml` y los `tests/test_*_contract.py` (33 ficheros) fijan roles de
  AgentGateway, firewall del edge, external-dns, Velero…

## 3. Stack

| pieza | versión | para qué | no se usa en su lugar |
|---|---|---|---|
| Traefik (chart) | 40.2.0 | edge + LAN | nginx (retirado) |
| MetalLB, cert-manager, external-dns, external-secrets, Kyverno, Velero, Harbor, CNPG, Keycloak (`keycloak-next`) | por `platform/*`, `networking/*` | plataforma | — |
| Ansible + Terraform OVH + `scripts/ovh_install.py` | — | KS-5 (3 control-plane) | scripts a mano |
| Python 3.12 + PyYAML 6.0.2 | CI | tests de contrato | — |

## 4. Componentes compartidos

| concepto | pieza canónica | ruta | quién la usa |
|---|---|---|---|
| Rutas públicas del edge | `networking/traefik-edge/<app>-public.yaml` | ídem | todas las apps públicas |
| Rutas LAN | `networking/traefik-lan/` (`canonical-hosts-lan.yaml`) | ídem | toda la LAN (+ AdGuard) |
| Postgres compartido | `databases/postgres-shared` | ídem | litellm, langfuse, firecrawl, document-intake, auto-reply |
| Catálogo de roles Keycloak | `platform/keycloak-next/ROLES.yaml` | ídem | AgentGateway |
| Bootstrap de los hooks PostSync de Keycloak (trap de limpieza, `fail`, login admin con reintentos, `kget`, líneas no vacías) | `platform/keycloak-next/scripts/kc-admin-common.sh` | ídem | los hooks de keycloak-next; único sitio de estas funciones |
| Reconciliadores de clients de servicio de Keycloak (mapper de audiencia, scope de roles, mint y comprobación exacta del token) | `platform/keycloak-next/scripts/keycloak-reconcile-lib.sh` (carga después de `kc-admin-common.sh`) | ídem | chat-agentgateway, jarvis-echo, hermes-enviar, agentgateway-chat-mcp, domain-roles |
| Secretos desde 1Password | ClusterSecretStore `onepassword-connect` sobre 1Password Connect (copia local del vault, sin cupo diario) + ES en `refreshPolicy: OnChange` (Kyverno `externalsecret-onepassword-onchange`) + `onepassword-change-detector` (force-sync de lo que cambió, cada 4 h, en los dos stores). Transición: Kyverno `externalsecret-onepassword-to-connect` admite los ES escritos para `onepassword` (`key: ítem/campo`) como de `onepassword-connect` (`key: ítem` + `property`) hasta reescribir los ~30 repos. El store `onepassword` (SDK, cupo de 1000/día de la cuenta) queda para las PushSecret y como respaldo si Kyverno cae. Kyverno `externalsecret-alibaba-plan-only-litellm` (POLICY 8, Enforce, DGX-619/626) deniega al admitir todo ExternalSecret fuera del ns `litellm` cuyo `remoteRef.key`, `dataFrom.extract.key` o `dataFrom.find.name.regexp` apunte a `alibaba-model-studio*`; las claves del Token Plan de Alibaba solo se leen allí, el resto va por el plan-gateway. No ve Secrets creados a mano. Recoger un secreto nuevo o rotado: la regla única es el comentario de `platform/external-secrets/cluster-secret-store-onepassword.yaml` (nuevo = crear el ES; rotado = force-sync de ESE ES o del CES, o el detector; nunca reiniciar ESO ni anotar el store) | `platform/onepassword-connect/`, `platform/external-secrets/`, `platform/kyverno/policies.yaml` | todo ExternalSecret del clúster |
| Secretos in-cluster entre namespaces (sin 1Password, sin cupo) | ClusterSecretStore `kubernetes-control-nexus-pagos`: SA `eso-control-nexus-pagos-reader` (ns `hermes`) + Role/RoleBinding de SOLO `get` por resourceNames sobre `dgx-dashboard-pagos` y `dgx-dashboard-pagos-decision` (ns `control-nexus`) — patrón `kubernetes-cnpg` | `platform/external-secrets/cluster-secret-store-control-nexus-pagos.yaml` | Hermes (plugin `confirmar-pago`, dgx.app.pagos.v1) |
| Runbooks | `docs/runbook*.md`, `docs/disaster-recovery.md` | `docs/` | operación |
| Volumen local de un nodo (1 réplica, strict-local, reclaim Delete, WaitForFirstConsumer) | StorageClass longhorn-strict-local | kubernetes/storage/longhorn-strict-local.yaml (listada en kustomization.yaml raíz y en kubernetes/storage/kustomization.yaml) | Frigate (frigate-config y frigate-media en ubuntu, INFRA-701). Sus PVC llevan argocd.argoproj.io/sync-options: Prune=false,Delete=false: borrar el PVC destruye el dato |

## 5. Cómo se construye aquí

Host nuevo = IngressRoute en `networking/traefik-{edge,lan}/` + línea en `kustomization.yaml` + rewrite en AdGuard + (edge)
`wildcard-cert`/TLS store. **Un cambio de naturaleza destructiva** (KS-5, OVH reinstall) exige las confirmaciones
explícitas del README (`CONFIRM_OVH_REINSTALL=…`) y `docs/runbook.md`. `docs/architecture.md` describe el estado
objetivo KS-5; el estado actual lo manda el cluster. StorageClass nueva = fichero en kubernetes/storage/ + línea en el
kustomization.yaml raíz. El kustomization.yaml de kubernetes/storage/ no lo consume ninguna Application (solo
scripts/verify_sauvage_longhorn.sh): un fichero que solo esté ahí no llega al clúster. Ejemplo: longhorn-prod-nvme.yaml
(longhorn-prod-nvme y longhorn-dev) no está en el raíz.

## 6. Tests y validaciones

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v   # 33 ficheros de contrato
python3 -m unittest discover -s tests -p 'test_keycloak_rbac_*.py' -v
kustomize build .                                           # reusable-ci
```
Nº de casos: **pendiente de medir**.

## 7. CI/CD y despliegue

- `ci.yml` (`arc-k8s`): `reusable-ci.yml@96ec4d91…` + jobs de contrato (reconciliador de roles Keycloak con imagen fijada,
  auditor RBAC, registro `ROLES.yaml`, operabilidad Velero, propiedad de external-dns…), `duplicados.yml`,
  `pr-review.yml`, `release.yml`.
- Despliegue: merge a `main` → ArgoCD (`k8s-infra`, `postgres-shared`, `traefik-*`). **Validación en producción**: probar el
  host nuevo extremo a extremo (`curl -I https://<host>` por edge y por LAN) y `kubectl get applications -n argocd`;
  Synced ≠ funcionando. Pendiente de ejecutar.

### Sync por olas y salud de los CronJob (DGX-626)

- `k8s-infra` sincroniza por olas (`argocd.argoproj.io/sync-wave`): la operación solo pasa a la ola siguiente si los recursos
  de las anteriores están sanos. Un CronJob cuyo último Job falla deja la operación `Failed` y **bloquea cualquier cambio de
  una ola posterior**. Caso: la ClusterPolicy `externalsecret-alibaba-plan-only-litellm` (DGX-626) quedó atrapada en la ola 1
  por el detector `keycloak/keycloak-role-drift` de la ola 0.
- El detector falla **a propósito** cuando hay drift: su fallo es su función, y la visibilidad va por la alarma
  `K8sCronJobFailed` (topic Crons), no por ArgoCD.
- Arreglo del patrón: health global `resource.customizations.health.batch_CronJob` → `Healthy` en el `argocd-cm`
  (pocharlies-org/k8s-gitops-pocharlies#515, pendiente del sync de la app `argocd`). Nota del architect:
  `nota-architect-health-detector.md` en DGX-626; el drift que lo disparó, en SC-2005.
- ArgoCD **no reintenta solo** un sync `Failed` del mismo SHA (7bc9dff: Failed a las 08:26, detector verde a las 08:30, sin
  repetición). Tras sanar la causa se re-dispara con un commit nuevo en `main` (este cambio es el ejemplo), nunca con
  `argocd app sync` a mano.

## 8. Decisiones y trampas

- `README`/`docs/architecture.md` aún dicen k3s v1.32.5 y «ubuntu único control-plane»: el cluster real tiene `ks5-cp-1/2/3`
  (README desfasado).
- El edge no ve namespaces fuera de su allowlist: una ruta pública «en el namespace de la app» no funciona.
- `prune: false` en `k8s-infra`: quitar un fichero de `kustomization.yaml` no borra el recurso en el cluster.
- `docs/runbook-cloudflare-lan-record-budget.md`: límite de registros LAN en Cloudflare; leer antes de añadir hosts.
- ExternalSecret de 1Password (INFRA-511): un commit que solo cambie la clave o el store de un ES escrito para
  `onepassword` no marca su app OutOfSync (ArgoCD ignora esos campos, `argocd/values.yaml` de k8s-gitops-pocharlies):
  reescríbelo a la forma de Connect. Reconstrucción total: Harbor lee sus secretos por Connect y la imagen de Connect
  está en Harbor; ver `docs/disaster-recovery.md`.
- 1Password Connect (INFRA-511/520): Deployment de réplica única, emptyDir, sin PVC — SPOF aceptado (si cae, ESO
  conserva el último valor de cada Secret). Las 13 PushSecret de Hermes (ns hermes) permanecen en el store SDK
  `onepassword`: el proveedor Connect no implementa SecretExists, que exige updatePolicy IfNotExists; por eso el
  store SDK sigue vivo y gasta cupo. Credenciales de arranque fuera de banda, sin ES; rotación en la sesión semanal.
  Runbook: `docs/runbook-1password-connect.md`.
- Un ExternalSecret fuera de `litellm` con un ítem `alibaba-model-studio*` se rechaza al aplicar (mensaje DGX-619;
  POLICY 8). Usa el plan-gateway. `failurePolicy: Ignore`: si Kyverno cae, se admite. Sin medir: un ítem referido por
  UUID en vez de por título y `find.tags`/`find.path` no están cubiertos.
- Envío de correo de Hermes (INFRA-676, épica INFRA-480): el client `hermes-enviar` (service account, roles
  exactamente `agentgateway-read:workspace` y `agentgateway-write:workspace-envio`, `fullScopeAllowed=false`) y los
  roles `agentgateway-write:workspace-envio` y `:workspace-borrador` los crea `platform/keycloak-next` por hooks
  PostSync (`hermes-enviar-client.yaml` en la ola 24, `agentgateway-domain-roles` en la 19), nunca a mano. El hook no
  gestiona el secreto: se siembra en 1Password `hermes-kc-enviar` tras el primer sync (RUNBOOK 18) y tiene que estar
  antes del chart de Hermes. `workspace-borrador` tiene un único titular revisado, `secretaria-skirmshop` (solo redacta borradores; nunca
  envía). El hook solo lo tolera; la concesión en el realm la hace el proceso de identidades de secretaria (INFRA-494).
  Entre el merge y la concesión `keycloak-role-drift` da `DRIFT:` (el catálogo declara un titular que el realm aún no
  tiene). En el primer sync,
  `keycloak-role-drift` puede dar `DRIFT:` hasta que acaban los hooks; se limpia solo.
- Navegador de las secretarias (SC-2238): `agentgateway-write:browser-navegacion` (27 tools de `/browser`, regla en
  k8s-agentgateway-pocharlies#191) y sus cuatro titulares (`service-account-hermes-secretaria`, `-dani`, `-leila` y `-casa`; el de `-skirmshop` queda fuera por
  veredicto de Security, DGX-760 comentario 30717: lectura de negocio, INFRA-492) están declarados en
  `ROLES.yaml`, `PRINCIPALS.md` y `ROUTE-ROLES.md`; `tests/test_keycloak_rbac_browser_navegacion_contract.py` fija que
  las dos copias de la lista son el mismo conjunto de 27 (corte de Security, sin las 13 sensibles). El rol NO está en `ROLE_NAMES` del hook `agentgateway-domain-roles`: se
  crea y se concede en el realm a mano (API admin, sin composites ni el rol pelado, admin events enlazados al ticket), y
  hasta entonces `keycloak-role-drift` da `DRIFT:` (rol catalogado que el realm aún no tiene). Orden: este catálogo se
  fusiona ANTES de crear/conceder el rol, y la concesión sigue de inmediato para cerrar la ventana.
- longhorn-single (1 réplica, Delete, sin dataLocality) existe solo a mano en el clúster, no está en git y no se usa: no
  garantiza en qué nodo cae la réplica. Para un volumen local de un nodo, longhorn-strict-local.

Última verificación contra el código: 2026-10-08 · e5fe657 (origin/main)
