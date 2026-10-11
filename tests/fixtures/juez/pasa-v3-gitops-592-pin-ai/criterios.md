# DGX-817 · criterios del 00-spec.md

- [ ] C1. La línea `pin/qwen38-tp3-20261010` integra la ventana: `git merge origin/pin/sparks-ventana-20261010` (nunca rebase) y los conflictos resueltos a favor del TP=3 en el manifiesto del residente.
- [ ] C2. Overlay nuevo `overlays/qwen38-tp3-ventana-20261010`: el render TP=3 de `overlays/ornith-sm121v5-lmheadw4-20260721` de esta línea (head dgx2, worker dgx1, worker-dgx3) más el componente `k8s/components/sparks-ventana-pausa-20261010`, para que el PreSync pase con el árbitro en sync-paused o recovering. Conserva el PostSync `llm-deploy-resume`. No entra ningún Job de sonda.
- [ ] C3. Los tres rangos del residente TP=3 llevan la receta del contexto:
- [ ] C4. Tests en tools/ (rojo antes, verde después), en `test_qwen38fn_tp3_manifest.py` o donde estén los del TP=3:
