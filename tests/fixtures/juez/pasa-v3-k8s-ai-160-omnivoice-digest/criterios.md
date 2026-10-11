# SC-2303 · criterios del 00-spec.md

- [ ] `voice/omnivoice-dgx2.yaml` cambia una sola línea: la `image:` del contenedor `omnivoice-tts` de `omnivoice-tts-nvfp4`. Comando: `git diff origin/main --stat` muestra 1 fichero, 1 inserción, 1 borrado.
- [ ] La imagen nueva conserva el repo y el tag y solo cambia el digest: `harbor.lan.e-dani.com/homelab/dgx-infra/omnivoice:ci-b46d476ecd320965f65dd983288129ad47d1981d@sha256:e642001d741655228754005749a8beaa609def585658a1b57a45567ee37381ad`. Comando: `git diff origin/main | grep '^[+-] '`.
- [ ] Ningún otro manifiesto cambia: ni el residente qwen38, ni el árbitro, ni nada de `k8s/`, `overlays/` o `lab/`. Comando: `git diff origin/main --name-only` devuelve solo `voice/omnivoice-dgx2.yaml`.
- [ ] El digest nuevo existe en Harbor y el viejo no (evidencia en la descripción de la PR: GET del manifiesto 200 frente a 404).
