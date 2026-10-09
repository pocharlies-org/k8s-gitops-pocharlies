# DGX-777 · evidencia

Dónde: worktree del repo, rama DGX-777-ai-vuelta-fadbbdd, 2026-10-09.

- Test previo, sobre origin/deploy/prod: `grep -q 'targetRevision: fadbbdda1a6a3f85aaeed7138f924cd066210e8c' apps/ai.yaml` -> FAIL (esperado)
- Mismo test tras el cambio -> PASS
- YAML parsea: `python3 -c 'import yaml; yaml.safe_load(open("apps/ai.yaml"))'` -> PASS, `spec.source.targetRevision` = fadbbdda1a6a3f85aaeed7138f924cd066210e8c
- Commit existe: `gh api repos/pocharlies-org/k8s-ai-pocharlies/commits/fadbbdda1a6a3f85aaeed7138f924cd066210e8c` -> 200, «DGX-684: brazo test/dgx-680-mtp-k1 — MTP k=1 plano …»

| criterio | resultado |
|---|---|
| C1 targetRevision vigente = fadbbdda (líneas 180 y 1062, comentadas, intactas) | PASS |
| C2 único fichero de la spec (apps/ai.yaml) + YAML válido | PASS |
| C3 fadbbdda existe en k8s-ai-pocharlies | PASS |
