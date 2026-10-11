# DGX-818 · criterios del 00-spec.md

- [ ] C1. Línea nueva `pin/glm53-ventana-20261010` desde el head de `pin/sparks-ventana-20261010` (92fb200). Trae de main con `git checkout origin/main -- …` solo `k8s/glm53-tp3/` y lo que este necesite. Todo lo demás del render de `ai` sigue siendo el de la ventana.
- [ ] C2. Overlay `overlays/glm53-tp3-ventana-k4-20261010`:
- [ ] C3. Los tres rangos de GLM llevan la receta NCCL del contexto, con el orden dgx3,dgx1,dgx2. Lo que la receta de GLM fija en contra de ella (`NCCL_IB_SUBNET_AWARE_ROUTING=1` en `recipe.env`, o lo que meta el entrypoint de la imagen) se anula solo en este overlay. El entrypoint no la pisa: compruébalo leyendo el entrypoint de la imagen (`images/glm53-kindling` y el compose fijado). ARX (`VLLM_ARX_RING=1`) se queda como está.
- [ ] C4. Tests en tools/:
