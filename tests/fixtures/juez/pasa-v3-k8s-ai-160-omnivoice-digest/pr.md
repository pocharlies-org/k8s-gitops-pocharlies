SC-2303: omnivoice-tts-nvfp4 repinea al digest vivo de ci-b46d476e (Harbor borró el pinneado)

## Qué

Request SC-2303. `omnivoice-tts-nvfp4` está en `ImagePullBackOff` porque Harbor ya no tiene el digest pinneado. Esta PR cambia solo el digest de `voice/omnivoice-dgx2.yaml`: de `sha256:1300475e…` a `sha256:e642001d…`. El tag (`ci-b46d476ecd32…`) y el commit de dgx-infra (`b46d476e`) son los mismos.

## Por qué

- El 28-09 el run 36455204368 (push de b46d476e) construyó `1300475e…` y `3325203` lo pinneó.
- El 29-09 a las 01:35Z se relanzó ese mismo run (intento 2, porque el re-pin automático había fallado). Reconstruyó b46d476e, empujó el tag `ci-b46d476e…` al digest nuevo `e642001d…` y dejó `1300475e…` sin tag.
- El GC semanal de Harbor (sábados 04:00Z, `delete_untagged=true`) borró el digest sin tag el 03-10 a las 04:00Z (job 8608, líneas «delete the untagged artifact … sha256:1300475e…»).
- El nodo siguió corriendo su copia en caché hasta que el kubelet la recolectó al bajar la voz a 0 en la ventana de DGX-810. Desde ahí el pull da `NotFound`.

## Evidencia

- `GET /v2/homelab/dgx-infra/omnivoice/manifests/sha256:e642001d…` devuelve 200 (índice OCI con el manifiesto arm64 `4346e1dd…` y su atestado); el mismo GET con `1300475e…` devuelve 404.
- `e642001d…` lo construyó el CI de dgx-infra desde b46d476e con los mismos pins del Dockerfile (torch nightly `dev20260921`, omnivoice `28bc0889`). Nunca se ha desplegado (sin pulls en Harbor): la prueba es el humo de voz tras el rollout.

## Después del merge (no es de esta PR)

ArgoCD `voice` (sync automático sobre `main`) hace el rollout. Compruebo que el pod queda Running y Ready y que `/v1/audio/speech` sintetiza con la voz `leila_clean_16s`. Si el humo falla, el plan B es el digest de `ci-82e849db` (`3645bb20…`), que sí corrió en producción.

No toca el residente qwen38, el árbitro ni la app `ai`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

