# Evidencia · INFRA-1364 P1a (keep- en los reusable de k8s-gitops)

Rama: `INFRA-1364-p1a-keep-tag` · Repo: `pocharlies-org/k8s-gitops-pocharlies` (trunk `main`)
Ejecutado en: `/home/dibanez/k8s/k8s-gitops-pocharlies/.claude/worktrees/INFRA-1364-p1a` (worktree sobre `origin/main` @ 5fd7680), 2026-11-15.

## C1 — test que debe fallar antes de fusionar (medido en Harbor)

Comando del spec (CREDS = credencial de robot de Harbor usada por CI; lectura del endpoint de tags → 200):

```
D=$(curl -sk -u "$CREDS" "https://harbor.lan.e-dani.com/api/v2.0/projects/homelab/repositories/correo-app/artifacts?page_size=1" | jq -r '.[0].digest')
curl -sk -u "$CREDS" "https://harbor.lan.e-dani.com/api/v2.0/projects/homelab/repositories/correo-app/artifacts/${D/:/%3A}/tags" | jq -r '.[].name' | grep -cx "keep-${D:7:12}"
```

Salida real (2026-11-15):

```
digest=sha256:95d4074725c661395a44b7f0d86acb192484948c3b49fcc264a46e5a90d38b01
tags del ultimo artefacto:
ci-0872a409519296c3944ba016ccda570633027b4d
C1 grep keep (esperado 0 antes del cambio): 0
```

**0** — el artefacto `ci-*` más reciente de `correo-app` (publicado antes de este cambio) no lleva `keep-95d4074725c6`. Tras fusionar y correr un release, el mismo comando debe dar **1** (C1-run, evidencia futura, no anticipable aquí).

## C1-render — tests del paso keep-

Comando: `python3 -m unittest tests/test_release_retry_idempotence.py`

```
Ran 26 tests in 23.861s
OK
```

Cubren, en ambos caminos (bucle de promoción de `reusable-release.yml` extraído verbatim + paso completo de `reusable-manifest-release.yml` contra la API Harbor falsa):

- `test_release_tags_and_keep_tag_land_on_the_index_digest` / `test_release_attaches_keep_tag_to_the_published_digest` — 201: el keep- se crea sobre el mismo manifest que los tags de release.
- `test_keep_409_on_the_same_digest_is_a_verified_success` — 409 de mismo digest = éxito verificado.
- `test_keep_409_on_another_digest_fails_the_job` — 409 cuyo tag resuelve a otro digest = el job falla.
- `test_keep_creation_failure_fails_the_job` — cualquier otro código (500 inyectado) = el job falla.

Render/contratos del repo (todos en verde tras el cambio):

```
python3 scripts/check-release-supply-chain.py  → Immutable image release supply-chain contract passed
python3 scripts/check-release-image-linkage.py → Release-to-manifest image digest linkage contract passed
python3 scripts/check-workflow-pins.py         → All third-party workflow dependencies are pinned to immutable commits
python3 scripts/check-manifest-promotion.py    → GitOps manifest PR-promotion contract passed
python3 -m unittest tests/test_company_release_contract.py → OK
```

Nota: `tests/test_release_image_linkage_runtime.py` y `tests/test_release_scan_gate_reports_findings.py` fallan en `setUpClass` con `TypeError: TarFile.extract() got an unexpected keyword argument 'filter'` — fallo del entorno local (python < 3.12), idéntico sobre `origin/main` limpio; en el runner ARC (python moderno) corren.

Duplicados: `company-duplicados` → sin duplicación nueva (ver informe de la PR).

## Criterios

- **C1**: mecanismo implementado en los dos reusable (paso keep- tras la verificación por digest, primitiva CreateTag 201/409 + verify, digest del index); test que debe fallar medido → 0 (arriba). El 1 corresponde al run real posterior al merge (C1-run).
- **C1-render**: PASS — 26/26 en `test_release_retry_idempotence.py`, contratos de workflow en verde.
- **C1-run**: evidencia futura (run real tras el merge), no anticipable en esta PR.
- **Docs**: `ARCHITECTURE.md` §componentes compartidos registra el keep- del release como contrato aditivo (filas «Release de imágenes» y «Release de manifiestos»).
