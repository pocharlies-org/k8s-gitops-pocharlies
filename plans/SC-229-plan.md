# Plan SC-229 — semántica del exit code de shopify-picqer-order-audit

Sesión CTO: c6d16440-955a-4915-aafe-6ef0ef4c4689

## Decisión (CTO, no se reabre)
`Failed` = «no se pudo auditar». Hallazgos (`findings > 0`) = dato, exit 0.
Límite: el hallazgo no puede volverse invisible → mecanismo de visibilidad que YA exista
en el stack; el CTO falla el mecanismo antes de escribirse. Exit code y visibilidad se
mergean juntos.

## Hechos confirmados por el tech-lead (09-09-2026, vivo)
- Application `shopify-sync`: repo `github.com/pocharlies-org/k8s-shopify-sync-pocharlies`,
  targetRevision `main`, path `k8s`, Healthy/Synced.
- CronJob `shopify-picqer-order-audit` ns `skirmshop`: schedule `30 2 * * *`, imagen
  `harbor.e-dani.com/homelab/shopify-sync-app@sha256:28a84315…`.

## Partes
| parte | dueño | qué | verificación | done significa |
|---|---|---|---|---|
| A. Historias + criterios bajo SC-229 (semántica nueva, casos (a) y (b)) | pm | Jira | criterios comprobables | historias creadas |
| B. Auditoría de mecanismos de visibilidad existentes (vmalert/vmalertmanager, backup-alert-report, push de métricas) — SOLO lectura, candidatos + docs oficiales | sre | informe | docs citadas, receivers reales | CTO falla |
| C. Localizar repo de código del script + pipeline de imagen + bump de digest — SOLO investigación | developer | informe | path exacto + flujo de build | base para implementar |
| D. Implementar exit code según criterios de A → PR rama trunk del repo de código (+ bump digest GitOps cuando haya imagen) | developer | PR | qa casos (a)+(b) | PR abierto |
| E. Visibilidad del hallazgo con el mecanismo que falle el CTO | devops/developer | PR | qa | PR abierto |
| F. Veredicto qa (a)+(b) con evidencia; veredicto funcional pm | qa, pm | verdicto | — | cerrado |

Restricciones: nadie mergea ni pushea al tronco. PR siempre. El merge lo pulsa el CTO,
D y E juntos. Fuera de alcance: arreglar ORD18849/ORD18903.
