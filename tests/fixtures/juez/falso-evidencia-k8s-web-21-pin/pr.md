INFRA-807

## Alcance de esta PR

- C1: el diff es solo el pin: `newTag` pasa a un sha de 40 hex (`k8s/kustomization.yaml:15`) y el comentario del pin se actualiza (`k8s/kustomization.yaml:11-13`)
- C2: no se reconstruye: el único fichero cambiado es `k8s/kustomization.yaml` (líneas 11-13 y 15), ninguna ruta de `paths:` de `build.yml`, así que el merge no lanza otro build

## Qué cambia

`newTag` de `harbor.e-dani.com/homelab/web-edani` pasa de `ea6ee4551085bb3c71579d7f741b96657831c67a` a `ef0a15005746c58f5ba7134edb1b9feb69ca7088`, el commit de merge de P2 (INFRA-806, #20: home rediseñada). Es la segunda mitad del despliegue de INFRA-396: `build.yml` construye pero no despliega, ArgoCD sigue este pin.

## Evidencia de la imagen (la aporta el maker, no se juzga en el diff)

Run de `build.yml` sobre el commit de merge de P2, terminado en `success` (intento 2, tras reparar el login a Harbor en INFRA-819): https://github.com/pocharlies-org/k8s-web-pocharlies/actions/runs/38012152077

```
gh run list -R pocharlies-org/k8s-web-pocharlies --workflow build.yml --branch main --limit 3 --json headSha,conclusion
{"conclusion":"success","headSha":"ef0a15005746c58f5ba7134edb1b9feb69ca7088"}   <- sha de este pin
{"conclusion":"failure","headSha":"2e1a60757deac698454836932c269d3ffb77abd9"}
{"conclusion":"success","headSha":"80b4c7abdb34c7e3a200bf53eb9f023ebb9248af"}
```

`docker manifest inspect harbor.e-dani.com/homelab/web-edani:ef0a15005746c58f5ba7134edb1b9feb69ca7088` responde OK.

## Vuelta atrás

Revertir este commit (`newTag` de vuelta a `ea6ee4551085bb3c71579d7f741b96657831c67a`); sin migraciones ni secretos.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

