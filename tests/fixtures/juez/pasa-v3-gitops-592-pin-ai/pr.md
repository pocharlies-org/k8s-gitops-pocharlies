DGX-817: app ai vuelve a 01f9b4d (qwen38 TP=3 en la ventana; rollback de GLM; k8s-ai #159)

Jira: DGX-817

Ventana de los Sparks (11-10-2026, Dani): GLM TP=3 ya terminó sus medidas (decode, benchy y batería de calidad). `apps/ai.yaml` pasa de `66a75539c673a68ff02a014ae574d3598ee969ce` (path `overlays/glm53-tp3-ventana-k4-20261010`) a `01f9b4da163dcf4626e6d33db0c450fababd7e10` (k8s-ai #159, cabeza de la línea `pin/qwen38-tp3-20261010`) con el path `overlays/qwen38-tp3-ventana-20261010`, para pasar a qwen38 TP=3 su batería de calidad. Es exactamente lo de la #587 y el rollback documentado de GLM.

## Alcance de esta PR

- C2: la app ai vuelve al overlay qwen38-tp3-ventana-20261010

## Qué cambia

- `targetRevision` y `path` de `apps/ai.yaml`, y un comentario con el efecto, el arranque y el rollback. Nada más.
- GLM se retira y el prune quita sus tres rangos (cabeza en dgx3, workers en dgx1 y dgx2). Vuelven head, worker y worker-dgx3 de qwen38 y el PostSync `llm-deploy-resume`.
- El Secret `glm53-tp3-mentat` (ExternalSecret con `deletionPolicy: Retain`) queda retenido: se borra si GLM no se reactiva, porque es una condición de security.
- Arranque de qwen38: unos 33 min, con unos 20 min sin log tras «GPU KV cache size» (no es cuelgue). El tráfico va a Alibaba hasta que el residente responda.

## Rollback

Volver a GLM: `66a75539c673a68ff02a014ae574d3598ee969ce` con path `overlays/glm53-tp3-ventana-k4-20261010`.

## Verificación

- `gh api` sobre k8s-ai-pocharlies: el path `overlays/qwen38-tp3-ventana-20261010` existe en `01f9b4d` (`kustomization.yaml`, `patch-nccl-ring.yaml`) y `01f9b4d` es la cabeza actual de `pin/qwen38-tp3-20261010`.
- `apps/ai.yaml` parsea como YAML con el `targetRevision` y el `path` de arriba.
- El render de ese SHA y path es el mismo que midió la #587; no se ha tocado nada del overlay.

Efecto observable, lo mide la sesión en la ventana: «Connected all rings» sin `ibv_modify_qp 110`, KV ≥ 3,19 M, y la batería de calidad de qwen38 TP=3.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

