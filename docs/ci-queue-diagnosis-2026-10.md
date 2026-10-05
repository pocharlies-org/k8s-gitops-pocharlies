# Diagnóstico de la cola de CI — pocharlies-org

Ventana: 2026-09-28T03:42:58Z → 2026-10-05T03:42:58Z (generado 2026-10-05T03:42:58Z, UTC). Fuente: API de jobs de GitHub Actions (`created_at` vs `started_at`, re-runs por intento; un job aún en cola cuenta con su edad hasta ahora). Pools leídos de `infra/arc.yaml`: arc-k8s, arc-openclaw, x86-hermes. Los runs rápidos (<30 s de espera a nivel de run) se miden con `run_started_at` de la lista de runs (fila `(run rápido)`); el resto, job a job con la API de jobs.

Jobs medidos: 8128 · en cola ahora: 3

## Espera por repo × label

| repo | label | tipo | jobs | p50 | p95 | max |
| --- | --- | --- | --- | --- | --- | --- |
| hermes-agent | ubuntu-latest-32-core | sin-pool | 9 | 50748 s | 86401 s | 86401 s |
| hermes-agent | windows-latest-32-core | sin-pool | 1 | 54633 s | 54633 s | 54633 s |
| hermes-agent | ubuntu-latest-96-core | sin-pool | 1 | 54633 s | 54633 s | 54633 s |
| k8s-tomorrowland-pocharlies | arc-k8s | pool | 4 | 18104 s | 18107 s | 18107 s |
| sauvageclubbot | arc-k8s | pool | 1 | 1558 s | 1558 s | 1558 s |
| skirmshop-labels | arc-k8s | pool | 13 | 30 s | 1189 s | 1189 s |
| synapse | arc-k8s | pool | 17 | 23 s | 172 s | 172 s |
| x86-host-runtime-pocharlies | arc-k8s | pool | 152 | 23 s | 161 s | 193 s |
| k8s-openclaw-qwen36-pocharlies | arc-openclaw | pool | 48 | 16 s | 144 s | 338 s |
| k8s-socialmedia-pocharlies | arc-k8s | pool | 372 | 24 s | 143 s | 2567 s |
| k8s-litellm-pocharlies | arc-k8s | pool | 64 | 26 s | 117 s | 225 s |
| k8s-socialmedia-pocharlies | ubuntu-latest | github | 18 | 2 s | 77 s | 77 s |
| dgx-infra | arc-k8s | pool | 259 | 23 s | 65 s | 233 s |
| libreplay | arc-k8s | pool | 2 | 23 s | 61 s | 61 s |
| k8s-picqer-mcp-pocharlies | arc-k8s | pool | 3 | 29 s | 61 s | 61 s |
| agent-jake-browser-mcp-server | arc-k8s | pool | 2 | 24 s | 45 s | 45 s |
| openchamber-build-pocharlies | arc-k8s | pool | 49 | 28 s | 44 s | 75 s |
| k8s-shopify-admin-mcp-pocharlies | arc-k8s | pool | 3 | 23 s | 43 s | 43 s |
| k8s-gitops-pocharlies | arc-k8s | pool | 13 | 22 s | 39 s | 39 s |
| dgx-messages | arc-k8s | pool | 4 | 23 s | 39 s | 39 s |
| release-bot-pocharlies | arc-k8s | pool | 2 | 33 s | 38 s | 38 s |
| k8s-shopify-framework-pocharlies | arc-k8s | pool | 2 | 33 s | 38 s | 38 s |
| k8s-infra-pocharlies | arc-k8s | pool | 54 | 0 s | 38 s | 1145 s |
| hermes-agent | arc-k8s | pool | 3 | 30 s | 38 s | 38 s |
| skirmshop-brain-v2 | arc-k8s | pool | 14 | 24 s | 37 s | 37 s |
| opencode-company | arc-k8s | pool | 9 | 0 s | 37 s | 37 s |
| openchamber-build-pocharlies | self-hosted | github | 14 | 2 s | 37 s | 37 s |
| k8s-observability-pocharlies | arc-k8s | pool | 4 | 22 s | 35 s | 35 s |
| k8s-ai-pocharlies | arc-k8s | pool | 9 | 27 s | 34 s | 34 s |
| k8s-openclaw-qwen36-pocharlies | arc-k8s | pool | 7 | 21 s | 32 s | 32 s |
| company-crm | arc-k8s | pool | 5 | 16 s | 31 s | 31 s |
| k8s-brain-mcp-pocharlies | arc-k8s | pool | 1 | 30 s | 30 s | 30 s |
| openchamber | arc-k8s | pool | 2 | 25 s | 27 s | 27 s |
| skirmshop-brain-k8s | arc-k8s | pool | 2 | 23 s | 26 s | 26 s |
| k8s-synapse-pocharlies | arc-k8s | pool | 4 | 0 s | 25 s | 25 s |
| k8s-shopify-serial-numbers-pocharlies | arc-k8s | pool | 2 | 22 s | 23 s | 23 s |
| k8s-gbp-festivos-pocharlies | arc-k8s | pool | 5 | 23 s | 23 s | 23 s |
| agent-browser-extension | self-hosted | github | 1 | 23 s | 23 s | 23 s |
| agent-browser-extension | arc-k8s | pool | 2 | 23 s | 23 s | 23 s |
| op-mcp-personal | arc-k8s | pool | 5 | 0 s | 21 s | 21 s |
| agent-browser-server | arc-k8s | pool | 8 | 0 s | 21 s | 21 s |
| llm-status-ios | arc-k8s | pool | 7 | 0 s | 10 s | 10 s |
| hermes-agent | macos-latest | github | 1 | 9 s | 9 s | 9 s |
| hermes-agent | ubuntu-latest | github | 28 | 2 s | 4 s | 4 s |
| llm-status-ios | ubuntu-latest | github | 3 | 3 s | 3 s | 3 s |
| llm-status-ios | self-hosted | github | 1 | 3 s | 3 s | 3 s |
| x86-host-runtime-pocharlies | self-hosted | github | 1 | 2 s | 2 s | 2 s |
| skirmshop-brain-k8s | ubuntu-latest | github | 1 | 2 s | 2 s | 2 s |
| opencode-config-pocharlies | self-hosted | github | 1 | 2 s | 2 s | 2 s |
| opencode-config-pocharlies | arc-k8s | pool | 1 | 2 s | 2 s | 2 s |
| k8s-web-pocharlies | ubuntu-latest | github | 1 | 2 s | 2 s | 2 s |
| k8s-openclaw-qwen36-pocharlies | x86-hermes | pool | 1 | 2 s | 2 s | 2 s |
| hermes-agent | windows-latest | github | 1 | 2 s | 2 s | 2 s |
| x86-host-runtime-pocharlies | (run rápido) | run | 928 | 0 s | 0 s | 0 s |
| trisplit | (run rápido) | run | 14 | 0 s | 0 s | 0 s |
| test-kata | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| test-infra | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| terraform-provider-pritunl | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| terraform-aws-transfer-server | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| terraform-aws-pritunl | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| synapse-mac-bridge-py | (run rápido) | run | 1 | 0 s | 0 s | 0 s |
| synapse-document-intake | (run rápido) | run | 4 | 0 s | 0 s | 0 s |
| synapse-client | (run rápido) | run | 9 | 0 s | 0 s | 0 s |
| synapse | (run rápido) | run | 60 | 0 s | 0 s | 0 s |
| skirmshopshopifyapp | (run rápido) | run | 12 | 0 s | 0 s | 0 s |
| skirmshopes-theme | (run rápido) | run | 4 | 0 s | 0 s | 0 s |
| skirmshop-serial-numbers | (run rápido) | run | 4 | 0 s | 0 s | 0 s |
| skirmshop-monitoring | (run rápido) | run | 10 | 0 s | 0 s | 0 s |
| skirmshop-labels | (run rápido) | run | 75 | 0 s | 0 s | 0 s |
| skirmshop-gestoria | (run rápido) | run | 8 | 0 s | 0 s | 0 s |
| skirmshop-firecrawl | (run rápido) | run | 6 | 0 s | 0 s | 0 s |
| skirmshop-control-panel | (run rápido) | run | 4 | 0 s | 0 s | 0 s |
| skirmshop-chatbot | (run rápido) | run | 11 | 0 s | 0 s | 0 s |
| skirmshop-brain-v2 | (run rápido) | run | 170 | 0 s | 0 s | 0 s |
| skirmshop-brain-k8s | (run rápido) | run | 132 | 0 s | 0 s | 0 s |
| skirmshop-affiliate-api | (run rápido) | run | 4 | 0 s | 0 s | 0 s |
| skirmbooks-gestoria-src | arc-k8s | pool | 3 | 0 s | 0 s | 0 s |
| skirmbooks-gestoria-src | (run rápido) | run | 46 | 0 s | 0 s | 0 s |
| skirmbooks-drive-ingest | (run rápido) | run | 8 | 0 s | 0 s | 0 s |
| shopify-translation-app | (run rápido) | run | 8 | 0 s | 0 s | 0 s |
| shopify-sync-app | (run rápido) | run | 8 | 0 s | 0 s | 0 s |
| shopify-skirmshoptemplate | (run rápido) | run | 4 | 0 s | 0 s | 0 s |
| shopify-sii-app | (run rápido) | run | 13 | 0 s | 0 s | 0 s |
| shopify-product-creator | (run rápido) | run | 4 | 0 s | 0 s | 0 s |
| shopify-collections-tree-app | (run rápido) | run | 4 | 0 s | 0 s | 0 s |
| shopify-bundle-app | (run rápido) | run | 4 | 0 s | 0 s | 0 s |
| shopify-back-in-stock | (run rápido) | run | 8 | 0 s | 0 s | 0 s |
| shopify-app-framework | (run rápido) | run | 8 | 0 s | 0 s | 0 s |
| shared-infra | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| sc-pilot-sandbox | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| sauvageserver | (run rápido) | run | 4 | 0 s | 0 s | 0 s |
| sauvageclubbot | (run rápido) | run | 1 | 0 s | 0 s | 0 s |
| release-bot-pocharlies | (run rápido) | run | 35 | 0 s | 0 s | 0 s |
| refusal-probe | (run rápido) | run | 11 | 0 s | 0 s | 0 s |
| qwen38-flash-next-dgx-spark-sglang | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| qwen38-27b-rank1-refusal-projection | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| python-skeleton | (run rápido) | run | 3 | 0 s | 0 s | 0 s |
| proxy-claude | (run rápido) | run | 16 | 0 s | 0 s | 0 s |
| pocharlies-webgui | (run rápido) | run | 6 | 0 s | 0 s | 0 s |
| pocharlies-rag | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| pocharlies-openclaw | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| pocharlies-lora | (run rápido) | run | 4 | 0 s | 0 s | 0 s |
| pocharlies-gmail-cleaner | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| pocharlies-aiops | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| opencode-config-pocharlies | (run rápido) | run | 48 | 0 s | 0 s | 0 s |
| opencode-company | (run rápido) | run | 274 | 0 s | 0 s | 0 s |
| opencode-claude | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| openclaw-vault-tools-pocharlies | (run rápido) | run | 4 | 0 s | 0 s | 0 s |
| openclaw-mem | (run rápido) | run | 4 | 0 s | 0 s | 0 s |
| openchamber-company-board | (run rápido) | run | 6 | 0 s | 0 s | 0 s |
| openchamber-build-pocharlies | (run rápido) | run | 92 | 0 s | 0 s | 0 s |
| openchamber | (run rápido) | run | 46 | 0 s | 0 s | 0 s |
| op-safe | (run rápido) | run | 7 | 0 s | 0 s | 0 s |
| op-mcp-personal | (run rápido) | run | 41 | 0 s | 0 s | 0 s |
| oficinas-pocharlies | (run rápido) | run | 10 | 0 s | 0 s | 0 s |
| n8n-workflow-backups | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| n8n-k8s | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| mcp-whatsapp | (run rápido) | run | 4 | 0 s | 0 s | 0 s |
| mcp-telegram | (run rápido) | run | 4 | 0 s | 0 s | 0 s |
| mcp-sendcloud | (run rápido) | run | 4 | 0 s | 0 s | 0 s |
| mcp-openclaw | (run rápido) | run | 4 | 0 s | 0 s | 0 s |
| mcp-dgx | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| mcp-brain-search | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| mcp-aimharder | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| mcp-17track | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| llm-status-ios | (run rápido) | run | 157 | 0 s | 0 s | 0 s |
| llm-status | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| litellm-model-sync | (run rápido) | run | 4 | 0 s | 0 s | 0 s |
| libreplay | (run rápido) | run | 6 | 0 s | 0 s | 0 s |
| k8s-web-pocharlies | (run rápido) | run | 36 | 0 s | 0 s | 0 s |
| k8s-tomorrowland-pocharlies | (run rápido) | run | 10 | 0 s | 0 s | 0 s |
| k8s-teslamate-pocharlies | (run rápido) | run | 12 | 0 s | 0 s | 0 s |
| k8s-teslamate-mcp-pocharlies | (run rápido) | run | 8 | 0 s | 0 s | 0 s |
| k8s-tesla-pocharlies | (run rápido) | run | 12 | 0 s | 0 s | 0 s |
| k8s-synapse-pocharlies | (run rápido) | run | 72 | 0 s | 0 s | 0 s |
| k8s-stt-mcp-pocharlies | (run rápido) | run | 8 | 0 s | 0 s | 0 s |
| k8s-socialmedia-pocharlies | (run rápido) | run | 546 | 0 s | 0 s | 0 s |
| k8s-skirmshopshopifyapp-pocharlies | (run rápido) | run | 19 | 0 s | 0 s | 0 s |
| k8s-skirmshop-wiki-pocharlies | (run rápido) | run | 5 | 0 s | 0 s | 0 s |
| k8s-skirmshop-drive-mirror-pocharlies | (run rápido) | run | 15 | 0 s | 0 s | 0 s |
| k8s-skirmshop-control-panel-pocharlies | (run rápido) | run | 8 | 0 s | 0 s | 0 s |
| k8s-skirmshop-competitor-crawler-pocharlies | (run rápido) | run | 8 | 0 s | 0 s | 0 s |
| k8s-skirmbooks-pocharlies | (run rápido) | run | 41 | 0 s | 0 s | 0 s |
| k8s-shopify-translations-pocharlies | (run rápido) | run | 12 | 0 s | 0 s | 0 s |
| k8s-shopify-sync-pocharlies | (run rápido) | run | 8 | 0 s | 0 s | 0 s |
| k8s-shopify-sii-pocharlies | (run rápido) | run | 35 | 0 s | 0 s | 0 s |
| k8s-shopify-serial-numbers-pocharlies | (run rápido) | run | 3 | 0 s | 0 s | 0 s |
| k8s-shopify-product-ai-pocharlies | (run rápido) | run | 8 | 0 s | 0 s | 0 s |
| k8s-shopify-picker-pocharlies | (run rápido) | run | 18 | 0 s | 0 s | 0 s |
| k8s-shopify-label-pocharlies | (run rápido) | run | 17 | 0 s | 0 s | 0 s |
| k8s-shopify-collections-tree-pocharlies | (run rápido) | run | 12 | 0 s | 0 s | 0 s |
| k8s-shopify-chatbot-pocharlies | (run rápido) | run | 15 | 0 s | 0 s | 0 s |
| k8s-shopify-bundles-pocharlies | (run rápido) | run | 12 | 0 s | 0 s | 0 s |
| k8s-shopify-back-in-stock-pocharlies | (run rápido) | run | 12 | 0 s | 0 s | 0 s |
| k8s-shopify-affiliate-pocharlies | (run rápido) | run | 12 | 0 s | 0 s | 0 s |
| k8s-shopify-admin-mcp-pocharlies | (run rápido) | run | 18 | 0 s | 0 s | 0 s |
| k8s-serpientetool-pocharlies | (run rápido) | run | 6 | 0 s | 0 s | 0 s |
| k8s-playwright-mcp-pocharlies | (run rápido) | run | 11 | 0 s | 0 s | 0 s |
| k8s-picqer-mcp-pocharlies | (run rápido) | run | 18 | 0 s | 0 s | 0 s |
| k8s-openclaw-qwen36-pocharlies | (run rápido) | run | 620 | 0 s | 0 s | 0 s |
| k8s-offers-mcp-pocharlies | (run rápido) | run | 8 | 0 s | 0 s | 0 s |
| k8s-observability-pocharlies | (run rápido) | run | 157 | 0 s | 0 s | 0 s |
| k8s-litellm-pocharlies | (run rápido) | run | 152 | 0 s | 0 s | 0 s |
| k8s-libreplay-pocharlies | (run rápido) | run | 11 | 0 s | 0 s | 0 s |
| k8s-langfuse-pocharlies | (run rápido) | run | 11 | 0 s | 0 s | 0 s |
| k8s-jarvis-pocharlies | (run rápido) | run | 17 | 0 s | 0 s | 0 s |
| k8s-infra-pocharlies | (run rápido) | run | 328 | 0 s | 0 s | 0 s |
| k8s-gitops-pocharlies | (run rápido) | run | 332 | 0 s | 0 s | 0 s |
| k8s-gbp-festivos-pocharlies | (run rápido) | run | 16 | 0 s | 0 s | 0 s |
| k8s-firecrawl-pocharlies | (run rápido) | run | 8 | 0 s | 0 s | 0 s |
| k8s-document-intake-pocharlies | (run rápido) | run | 8 | 0 s | 0 s | 0 s |
| k8s-dgx-synapse-mcp-pocharlies | (run rápido) | run | 25 | 0 s | 0 s | 0 s |
| k8s-cv-pocharlies | (run rápido) | run | 3 | 0 s | 0 s | 0 s |
| k8s-company-crm-pocharlies | (run rápido) | run | 5 | 0 s | 0 s | 0 s |
| k8s-brain-mcp-pocharlies | (run rápido) | run | 15 | 0 s | 0 s | 0 s |
| k8s-blog-pocharlies | arc-k8s | pool | 6 | 0 s | 0 s | 0 s |
| k8s-blog-pocharlies | (run rápido) | run | 45 | 0 s | 0 s | 0 s |
| k8s-auto-reply-worker-pocharlies | (run rápido) | run | 11 | 0 s | 0 s | 0 s |
| k8s-ai-pocharlies | (run rápido) | run | 60 | 0 s | 0 s | 0 s |
| k8s-agentjake-browser-mcp-pocharlies | (run rápido) | run | 30 | 0 s | 0 s | 0 s |
| k8s-agentgateway-pocharlies | (run rápido) | run | 135 | 0 s | 0 s | 0 s |
| k8s-adguard-pocharlies | (run rápido) | run | 15 | 0 s | 0 s | 0 s |
| k3s-gitops | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| job-dsl-test | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| jarvis | (run rápido) | run | 25 | 0 s | 0 s | 0 s |
| home-assistant | (run rápido) | run | 6 | 0 s | 0 s | 0 s |
| hermes-quick-ack | (run rápido) | run | 6 | 0 s | 0 s | 0 s |
| hermes-agent | (run rápido) | run | 62 | 0 s | 0 s | 0 s |
| factura-mcp-server | (run rápido) | run | 4 | 0 s | 0 s | 0 s |
| docker-jenkins-slave-dind | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| docker-jenkins | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| dgx-messages | (run rápido) | run | 103 | 0 s | 0 s | 0 s |
| dgx-infra | (run rápido) | run | 845 | 0 s | 0 s | 0 s |
| dgx-control-ios | (run rápido) | run | 4 | 0 s | 0 s | 0 s |
| desktop-mcp | (run rápido) | run | 6 | 0 s | 0 s | 0 s |
| deepseek-v4-flash-rank1-refusal-projection | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| cursor-agents | (run rápido) | run | 6 | 0 s | 0 s | 0 s |
| company-vscode | (run rápido) | run | 11 | 0 s | 0 s | 0 s |
| company-crm | (run rápido) | run | 32 | 0 s | 0 s | 0 s |
| company-config-pocharlies | (run rápido) | run | 14 | 0 s | 0 s | 0 s |
| cofounderlab | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| cloudblue-knowledge | (run rápido) | run | 4 | 0 s | 0 s | 0 s |
| claude-ui | (run rápido) | run | 6 | 0 s | 0 s | 0 s |
| claude-local-router | (run rápido) | run | 14 | 0 s | 0 s | 0 s |
| claude-config | (run rápido) | run | 6 | 0 s | 0 s | 0 s |
| claude-codex-bridge | (run rápido) | run | 6 | 0 s | 0 s | 0 s |
| bambulab-openclaw | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| aurora | (run rápido) | run | 8 | 0 s | 0 s | 0 s |
| agent-jake-browser-mcp-server | (run rápido) | run | 27 | 0 s | 0 s | 0 s |
| agent-jake-browser-mcp-extension | (run rápido) | run | 45 | 0 s | 0 s | 0 s |
| agent-browser-server | (run rápido) | run | 60 | 0 s | 0 s | 0 s |
| agent-browser-extension | (run rápido) | run | 110 | 0 s | 0 s | 0 s |
| Qwen3.8-Flash-Next-NVFP4-vLLM-DGX-Spark-k8s | (run rápido) | run | 2 | 0 s | 0 s | 0 s |
| Peekaboo | (run rápido) | run | 15 | 0 s | 0 s | 0 s |
| MCP-instagram | (run rápido) | run | 4 | 0 s | 0 s | 0 s |

## Peores esperas (top 10)

- 86401 s — `hermes-agent#11·nix flake check` · ubuntu-latest-32-core · 10-02 16:02 → 16:02
- 86400 s — `hermes-agent#9 (PR 7)·nix flake check` · ubuntu-latest-32-core · 10-02 15:43 → 15:43
- 54633 s — `hermes-agent#1·JS & TS checks / JS & TS checks` · ubuntu-latest-32-core · 10-01 00:53 → 00:53
- 54633 s — `hermes-agent#1·OS-specific tests / Windows-only tests` · windows-latest-32-core · 10-01 00:53 → 00:53
- 54633 s — `hermes-agent#1·Rust tests / cargo test (bootstrap installer)` · ubuntu-latest-32-core · 10-01 00:53 → 00:53
- 54633 s — `hermes-agent#1·Python tests / Run tests` · ubuntu-latest-96-core · 10-01 00:53 → 00:53
- 50748 s — `hermes-agent#1·nix flake check` · ubuntu-latest-32-core · 10-01 00:53 → 00:53
- 18107 s — `k8s-tomorrowland-pocharlies#113·standard / Build images` · arc-k8s · 10-01 19:40 → 19:40
- 18107 s — `k8s-tomorrowland-pocharlies#113·standard / Contract surface` · arc-k8s · 10-01 19:40 → 19:40
- 18104 s — `k8s-tomorrowland-pocharlies#114·standard / Contract surface` · arc-k8s · 10-01 19:40 → 19:40

## Casos citados en el spec

- **skirmshop-labels#151**: 7 jobs, peor espera 1189 s (`skirmshop-labels#562·monorepo (lint + typecheck + test + compose)`)

## sin-pool (ningún listener ARC los sirve — caso C4)

| repo | label | jobs | edad máx. |
| --- | --- | --- | --- |
| hermes-agent | ubuntu-latest-32-core | 9 | 86401 s |
| hermes-agent | windows-latest-32-core | 1 | 54633 s |
| hermes-agent | ubuntu-latest-96-core | 1 | 54633 s |

## cancelados (infra vs usuario, regla en `ci_queue.classify_cancelled`)

| causa | jobs |
| --- | --- |
| usuario: reemplazado por push posterior (concurrencia) | 593 |
| infra: cancelado durante ejecución | 10 |
| infra: esperando un runner inexistente (label sin pool) | 4 |
| usuario: cancelado en cola | 1 |

Ejemplos (peor espera de cada causa):

- usuario: reemplazado por push posterior (concurrencia) — `hermes-agent#1·JS & TS checks / JS & TS checks`: 54633 s
- infra: cancelado durante ejecución — `skirmshop-labels#555·monorepo (lint + typecheck + test + compose)`: 213 s
- infra: esperando un runner inexistente (label sin pool) — `hermes-agent#11·nix flake check`: 86401 s
- usuario: cancelado en cola — `hermes-agent#4·nix flake check`: 70 s

## ocupación por hora (UTC)

| hora | jobs iniciados | espera máx. | en cola al inicio |
| --- | --- | --- | --- |
| 09-28 03 | 4 | 0 s | 0 |
| 09-28 04 | 3 | 0 s | 0 |
| 09-28 05 | 3 | 0 s | 0 |
| 09-28 06 | 16 | 27 s | 0 |
| 09-28 07 | 22 | 32 s | 0 |
| 09-28 08 | 21 | 0 s | 0 |
| 09-28 09 | 40 | 52 s | 0 |
| 09-28 10 | 23 | 37 s | 0 |
| 09-28 11 | 7 | 0 s | 0 |
| 09-28 12 | 1 | 0 s | 0 |
| 09-28 13 | 20 | 7 s | 0 |
| 09-28 14 | 28 | 37 s | 0 |
| 09-28 15 | 17 | 0 s | 0 |
| 09-28 16 | 16 | 7 s | 0 |
| 09-28 17 | 11 | 0 s | 0 |
| 09-28 18 | 19 | 51 s | 0 |
| 09-28 19 | 13 | 0 s | 0 |
| 09-28 20 | 22 | 37 s | 0 |
| 09-28 21 | 19 | 0 s | 0 |
| 09-28 22 | 37 | 61 s | 0 |
| 09-28 23 | 58 | 81 s | 1 |
| 09-29 00 | 36 | 24 s | 0 |
| 09-29 01 | 31 | 53 s | 0 |
| 09-29 02 | 10 | 0 s | 0 |
| 09-29 03 | 15 | 37 s | 0 |
| 09-29 04 | 27 | 0 s | 0 |
| 09-29 05 | 36 | 62 s | 0 |
| 09-29 06 | 35 | 468 s | 0 |
| 09-29 07 | 15 | 2567 s | 0 |
| 09-29 08 | 0 | 0 s | 0 |
| 09-29 09 | 10 | 44 s | 0 |
| 09-29 10 | 1 | 0 s | 0 |
| 09-29 11 | 30 | 65 s | 0 |
| 09-29 12 | 16 | 0 s | 0 |
| 09-29 13 | 14 | 0 s | 0 |
| 09-29 14 | 34 | 75 s | 0 |
| 09-29 15 | 3 | 0 s | 0 |
| 09-29 16 | 38 | 32 s | 0 |
| 09-29 17 | 60 | 32 s | 0 |
| 09-29 18 | 38 | 48 s | 0 |
| 09-29 19 | 42 | 32 s | 0 |
| 09-29 20 | 23 | 41 s | 0 |
| 09-29 21 | 48 | 338 s | 0 |
| 09-29 22 | 17 | 20 s | 0 |
| 09-29 23 | 20 | 24 s | 0 |
| 09-30 00 | 21 | 22 s | 0 |
| 09-30 01 | 31 | 22 s | 0 |
| 09-30 02 | 17 | 22 s | 0 |
| 09-30 03 | 23 | 0 s | 0 |
| 09-30 04 | 13 | 0 s | 0 |
| 09-30 05 | 30 | 23 s | 0 |
| 09-30 06 | 31 | 34 s | 0 |
| 09-30 07 | 31 | 22 s | 0 |
| 09-30 08 | 17 | 0 s | 0 |
| 09-30 09 | 13 | 0 s | 0 |
| 09-30 10 | 31 | 55 s | 0 |
| 09-30 11 | 4 | 0 s | 0 |
| 09-30 12 | 28 | 23 s | 0 |
| 09-30 13 | 37 | 0 s | 0 |
| 09-30 14 | 77 | 76 s | 0 |
| 09-30 15 | 98 | 225 s | 0 |
| 09-30 16 | 38 | 34 s | 0 |
| 09-30 17 | 34 | 34 s | 0 |
| 09-30 18 | 20 | 32 s | 0 |
| 09-30 19 | 19 | 0 s | 0 |
| 09-30 20 | 36 | 72 s | 0 |
| 09-30 21 | 69 | 210 s | 0 |
| 09-30 22 | 161 | 257 s | 1 |
| 09-30 23 | 293 | 204 s | 0 |
| 10-01 00 | 135 | 54633 s | 1 |
| 10-01 01 | 4 | 0 s | 0 |
| 10-01 02 | 7 | 0 s | 0 |
| 10-01 03 | 22 | 0 s | 0 |
| 10-01 04 | 7 | 0 s | 0 |
| 10-01 05 | 18 | 0 s | 0 |
| 10-01 06 | 34 | 0 s | 0 |
| 10-01 07 | 32 | 22 s | 0 |
| 10-01 08 | 16 | 5 s | 0 |
| 10-01 09 | 59 | 79 s | 0 |
| 10-01 10 | 54 | 14621 s | 0 |
| 10-01 11 | 62 | 32 s | 0 |
| 10-01 12 | 45 | 33 s | 0 |
| 10-01 13 | 85 | 41 s | 0 |
| 10-01 14 | 50 | 43 s | 0 |
| 10-01 15 | 39 | 23 s | 0 |
| 10-01 16 | 103 | 54 s | 0 |
| 10-01 17 | 95 | 37 s | 0 |
| 10-01 18 | 166 | 18107 s | 0 |
| 10-01 19 | 179 | 1189 s | 0 |
| 10-01 20 | 149 | 1189 s | 0 |
| 10-01 21 | 173 | 1558 s | 0 |
| 10-01 22 | 153 | 105 s | 0 |
| 10-01 23 | 90 | 23 s | 0 |
| 10-02 00 | 89 | 23 s | 0 |
| 10-02 01 | 39 | 0 s | 0 |
| 10-02 02 | 17 | 0 s | 0 |
| 10-02 03 | 74 | 53 s | 0 |
| 10-02 04 | 28 | 0 s | 0 |
| 10-02 05 | 25 | 0 s | 0 |
| 10-02 06 | 30 | 32 s | 0 |
| 10-02 07 | 37 | 36 s | 0 |
| 10-02 08 | 38 | 0 s | 0 |
| 10-02 09 | 63 | 61 s | 0 |
| 10-02 10 | 25 | 43 s | 0 |
| 10-02 11 | 54 | 45 s | 0 |
| 10-02 12 | 24 | 52 s | 0 |
| 10-02 13 | 47 | 23 s | 0 |
| 10-02 14 | 25 | 1022 s | 0 |
| 10-02 15 | 118 | 86401 s | 0 |
| 10-02 16 | 99 | 35 s | 0 |
| 10-02 17 | 78 | 38 s | 0 |
| 10-02 18 | 102 | 65 s | 0 |
| 10-02 19 | 70 | 72 s | 0 |
| 10-02 20 | 59 | 22 s | 0 |
| 10-02 21 | 126 | 208 s | 0 |
| 10-02 22 | 128 | 58 s | 0 |
| 10-02 23 | 54 | 0 s | 0 |
| 10-03 00 | 25 | 39 s | 0 |
| 10-03 01 | 16 | 0 s | 0 |
| 10-03 02 | 26 | 0 s | 0 |
| 10-03 03 | 65 | 31 s | 0 |
| 10-03 04 | 38 | 21 s | 0 |
| 10-03 05 | 3 | 0 s | 0 |
| 10-03 06 | 11 | 0 s | 0 |
| 10-03 07 | 146 | 38 s | 0 |
| 10-03 08 | 20 | 0 s | 0 |
| 10-03 09 | 63 | 52 s | 0 |
| 10-03 10 | 57 | 22 s | 0 |
| 10-03 11 | 71 | 32 s | 0 |
| 10-03 12 | 61 | 7 s | 0 |
| 10-03 13 | 57 | 23 s | 0 |
| 10-03 14 | 36 | 37 s | 0 |
| 10-03 15 | 63 | 59 s | 0 |
| 10-03 16 | 55 | 71 s | 0 |
| 10-03 17 | 57 | 0 s | 0 |
| 10-03 18 | 83 | 35 s | 0 |
| 10-03 19 | 57 | 31 s | 0 |
| 10-03 20 | 102 | 28 s | 0 |
| 10-03 21 | 104 | 33 s | 0 |
| 10-03 22 | 85 | 69 s | 0 |
| 10-03 23 | 119 | 73 s | 0 |
| 10-04 00 | 35 | 0 s | 0 |
| 10-04 01 | 10 | 22 s | 0 |
| 10-04 02 | 13 | 61 s | 1 |
| 10-04 03 | 0 | 0 s | 0 |
| 10-04 04 | 5 | 0 s | 0 |
| 10-04 05 | 2 | 0 s | 0 |
| 10-04 06 | 19 | 46 s | 0 |
| 10-04 07 | 60 | 91 s | 0 |
| 10-04 08 | 104 | 108 s | 0 |
| 10-04 09 | 136 | 68 s | 0 |
| 10-04 10 | 82 | 52 s | 0 |
| 10-04 11 | 56 | 31 s | 0 |
| 10-04 12 | 78 | 22 s | 0 |
| 10-04 13 | 63 | 33 s | 0 |
| 10-04 14 | 75 | 27 s | 0 |
| 10-04 15 | 30 | 0 s | 0 |
| 10-04 16 | 34 | 0 s | 0 |
| 10-04 17 | 180 | 1145 s | 0 |
| 10-04 18 | 28 | 23 s | 0 |
| 10-04 19 | 15 | 24 s | 0 |
| 10-04 20 | 47 | 22 s | 0 |
| 10-04 21 | 70 | 69 s | 0 |
| 10-04 22 | 55 | 31 s | 0 |
| 10-04 23 | 64 | 29 s | 0 |
| 10-05 00 | 26 | 0 s | 0 |
| 10-05 01 | 6 | 0 s | 0 |
| 10-05 02 | 12 | 55 s | 0 |
| 10-05 03 | 6 | 38 s | 6 |

## Conclusiones

- p50 = 0 s · p95 = 28 s · max = 86401 s (jobs medidos: 8128)
- Solo jobs de pool ARC (labels arc-k8s, arc-openclaw, x86-hermes): p95 = 97 s · max = 18107 s (jobs: 1164)
- Concurrencia máxima en ejecución: **28** en pool ARC · 92 en total (incluye GitHub-hosted).
- Hora con peor espera: 10-02 15 UTC.
- Para P3 (maxRunners): pico ARC en ejecución = 28; con el p95 de pool ARC en 97 s, dimensionar ≥ 42 runners.
- Para P4 (N minutos de alerta): p95 de pool ARC = 97 s ≈ 1.6 min; la espera máx. medida fue 86401 s.
