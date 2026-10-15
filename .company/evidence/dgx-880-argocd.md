# DGX-880 · P9 · evidencia

Dónde corrió: worktree `agent-a96b7258ea4b7a992` de `k8s-gitops-pocharlies`, rama `dgx-880-argocd` sobre `origin/deploy/prod` 9daf03d, el 2026-10-15.
Lo que cambia: `apps/correo.yaml` (nuevo), una línea en `kustomization.yaml` y `tests/test_correo_application.py` (nuevo).

## 1. El test falla primero (commit d74ed5f, sin `apps/correo.yaml`)

Comando: `python3 -m unittest tests.test_correo_application`. Resultado: FAIL.

```
FileNotFoundError: [Errno 2] No such file or directory: '.../apps/correo.yaml'
Ran 4 tests in 0.002s
FAILED (errors=4)
```

## 2. Pasa con la Application (commit 36bb905)

Comandos: `python3 -B -m unittest tests.test_correo_application -v` y la suite entera con `python3 -B -m unittest discover -s tests -p 'test_*.py'`. Resultado: PASS.

```
test_namespace_is_created_restricted ... ok
test_root_kustomization_includes_application ... ok
test_sync_is_manual_until_the_first_sync ... ok
test_two_sources_chart_by_oci_and_values_repo ... ok
Ran 4 tests            (suite entera: Ran 73 tests, OK; el tronco tenía 69)
```

## 3. Cada propiedad protegida hace fallar el test

Comando: 11 mutaciones de `apps/correo.yaml`, una a una, con el fichero restaurado después de cada una. Resultado: PASS (las 11 detectadas).

```
DETECTADA  sync automatico            DETECTADA  repoURL con oci://
DETECTADA  enforce baseline           DETECTADA  values bajo path
DETECTADA  audit ausente              DETECTADA  ns de destino otro
DETECTADA  warn privileged            DETECTADA  sin CreateNamespace
DETECTADA  sin directory.recurse      DETECTADA  sin ServerSideApply
DETECTADA  chart por otra version
```

## 4. El raíz renderiza y solo añade la Application

Comando: `kubectl kustomize .` antes y después (el CI usa `kustomize build .`; aquí no está instalado el binario, y el `kubectl kustomize` integrado puede ser de otra versión). Resultado: PASS.

```
rc=0 en los dos renders; diff del tronco al cambio: 76 líneas añadidas, 0 quitadas
La Application renderizada lleva, por el parche del raíz, los ignoreDifferences de ExternalSecret, PushSecret, ClusterExternalSecret y Cluster
```

## 5. Los campos existen en el CRD vivo de ArgoCD v3.4.2

El CRD poda en silencio un campo que no conoce, y `managedNamespaceMetadata` mal escrito dejaría el ns sin sus etiquetas. Comando: un script (no va en el repo, necesita el clúster) que recorre `metadata` y `spec` de la Application contra `applications.argoproj.io` (`kubectl get crd`). Resultado: PASS.

```
PASS                       <- apps/correo.yaml
FAIL                       <- la misma Application con `managedNamespaceMetadataX` y `recurses`
  spec.sources[1].directory.recurses: campo desconocido (el CRD lo podaría)
  spec.syncPolicy.managedNamespaceMetadataX: campo desconocido (el CRD lo podaría)
```

Para repetirlo a mano, los tres campos que importan:

```
kubectl explain application.spec.syncPolicy.managedNamespaceMetadata --api-version=argoproj.io/v1alpha1   # "metadata in the given namespace (if CreateNamespace=true)"
kubectl explain application.spec.sources.directory.recurse --api-version=argoproj.io/v1alpha1             # <boolean>
kubectl explain application.spec.sources.ref --api-version=argoproj.io/v1alpha1                           # <string>
```

## 6. Duplicados

Comando: `company-duplicados --base origin/deploy/prod`. Resultado: PASS.

```
Sin duplicación nueva. (umbral >= 12 líneas, jscpd 5.4.0)
```

## 7. El publicador del chart

Comando: `gh run view 38690060471 -R pocharlies-org/correo-chart --json conclusion,headBranch,headSha` y su log. Resultado: PASS.

```
conclusion: success  headBranch: v0.1.0  headSha: aba3f4461541959b056d69639c81135f16426578
Pushed: harbor.lan.e-dani.com/homelab/charts/correo:0.1.0
Digest: sha256:7166aab3d30005e6fc0ed36d2abac530d1d91ffe3c947fd01fa99774fdcea49c
```

La fuente 1 es ese mismo `repoURL` + `chart` + `targetRevision`. Que ArgoCD pueda bajarlo no lo he medido: falta su credencial OCI (ver 8).

## 8. Lo que ya hay en el clúster y lo que falta (solo lectura)

Comandos: `kubectl get crd`, `get clustersecretstore`, `get cm`, `get secrets -n argocd -l argocd.argoproj.io/secret-type=repository`.

```
OK       CRD passwords.generators.external-secrets.io, externalsecrets.external-secrets.io, schedules.velero.io
OK       ClusterSecretStore onepassword-connect Valid/Ready; cm velero-fsb-volume-policy en ns velero (lo que usan los manifiestos de P8)
OK       langfuse (fuente 2 con `ref` y `path`, el molde) Synced/Healthy
FALTA    ningún Secret repository de ArgoCD apunta a harbor.lan.e-dani.com (DGX-916, de IT, en curso)
FALTA    ns `correo` y app `correo`: aún no existen (los crea el merge y el primer sync)
```

## Criterios

- C1, parte P9 (el manifiesto): PASS. `apps/correo.yaml` es multi-source (chart OCI `correo` 0.1.0 y values de `k8s-correo-pocharlies`), sin `automated`, con CreateNamespace y ServerSideApply, y el ns `correo` con Pod Security `restricted` en enforce, audit y warn (secciones 1 a 5).
- C1, parte en vivo (Synced/Healthy, etiqueta del ns, `/healthz`): no medida aquí. Se mide tras el merge y el primer sync.
