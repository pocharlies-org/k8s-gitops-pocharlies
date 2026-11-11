#!/usr/bin/env python3
"""Guard de tamaño de imágenes, estándar de la org (INFRA-536 C4 / INFRA-1298).

Comprueba el tamaño comprimido de una imagen contra `sizes-baseline.json` (la
línea base canónica de `docs/images/` en `k8s-infra-pocharlies`, generada por
`scripts/image-inventory.py`). Es la lógica del workflow
`reusable-image-guard.yml` — patrón de `duplicados.py` y
`alibaba-key-guard.py`: el workflow es fino, la lógica y su test viven aquí.

El comprimido se calcula como la suma de `layers[].size` del manifiesto que
produce `crane manifest --platform` (mismo método que el inventario de
INFRA-1296); el workflow lo baja con la imagen de crane fijada por digest y se
lo pasa por `--manifest`. Aquí no se toca la red: el script evalúa.

Ramas (las del 00-spec, cubiertas por tests/test_image_guard.py):
- por encima del tope absoluto → falla en AMBOS modos (techo duro);
- crecimiento sobre la línea base por encima del umbral → falla en modo
  `bloquear`, `::warning::` con exit 0 en modo `avisar`;
- imagen sin línea base → propone la entrada en el log y NO falla;
- entrada de la baseline con `comprimido: {"sin_dato": ...}` → se trata como
  sin línea base (la propone, no falla): el no-dato del inventario no puede
  poner en rojo a una imagen sana.

Salidas: 0 pasa/avisa/propone · 1 falla (tope, o crecimiento en `bloquear`) ·
2 uso inválido. El informe va a stdout y, si existe, a $GITHUB_STEP_SUMMARY.

Uso:
    image-guard.py --imagen REPO[@sha256:...|:tag] [--digest sha256:...]
                   --manifest MANIFIESTO.json|stdin --baseline sizes-baseline.json
                   [--modo bloquear|avisar] [--tope BYTES] [--crecimiento PCT]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
MODOS = ("bloquear", "avisar")


def fracaso(mensaje: str) -> None:
    print(f"image-guard: uso inválido: {mensaje}", file=sys.stderr)
    sys.exit(2)


def separar_imagen(imagen: str) -> tuple[str, str | None]:
    """(repo, digest_o_tag) — el tag va tras el último `:` solo si no hay `/`
    después (un registry con puerto lleva `host:puerto/repo`)."""
    if "@" in imagen:
        repo, _, digesto = imagen.partition("@")
        return repo, digesto
    cabeza, sep, cola = imagen.rpartition(":")
    if sep and "/" not in cola:
        return cabeza, cola
    return imagen, None


def leer_json(ruta: str, que: str):
    if ruta == "-":
        try:
            return json.load(sys.stdin)
        except json.JSONDecodeError as e:
            fracaso(f"el {que} por stdin no es JSON válido: {e}")
    p = Path(ruta)
    if not p.is_file():
        fracaso(f"{que} {ruta} no existe")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        fracaso(f"{que} {ruta} no es JSON válido: {e}")


def comprimido_del_manifiesto(manifiesto) -> int:
    capas = manifiesto.get("layers") if isinstance(manifiesto, dict) else None
    if not isinstance(capas, list) or not capas:
        fracaso("el manifiesto no trae `layers` (¿falta `--platform` al "
                "resolver un índice OCI?); no se puede medir el comprimido")
    total = 0
    for capa in capas:
        size = capa.get("size") if isinstance(capa, dict) else None
        if not isinstance(size, int) or size < 0:
            fracaso("el manifiesto trae una capa sin `size` entera")
        total += size
    return total


def propuesta(repo: str, digesto: str, comprimido: int) -> str:
    entrada = json.dumps({repo: {digesto: {
        "comprimido": comprimido,
        "descomprimido": {"sin_dato": "pendiente (crane export)"},
    }}}, indent=2)
    return (f"imagen sin línea base: se propone esta entrada para "
            f"`sizes-baseline.json` (no falla):\n```json\n{entrada}\n```")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--imagen", required=True,
                    help="repo@sha256:... o repo:tag (el repo es la clave de la baseline)")
    ap.add_argument("--digest", default="",
                    help="sha256:... resuelto por el workflow (crane digest); "
                         "obligatorio si --imagen no lleva @digest")
    ap.add_argument("--manifest", required=True,
                    help="JSON de `crane manifest --platform` (ruta o `-` por stdin)")
    ap.add_argument("--baseline", required=True,
                    help="ruta a sizes-baseline.json (formato docs/images/, INFRA-1296)")
    ap.add_argument("--modo", default="bloquear", choices=MODOS,
                    help="bloquear: el crecimiento falla · avisar: ::warning:: y pasa")
    ap.add_argument("--tope", type=int, default=0,
                    help="tope absoluto en bytes (0 = sin tope); aplica en ambos modos")
    ap.add_argument("--crecimiento", type=float, default=20.0,
                    help="crecimiento relativo admitido sobre la baseline, en %%")
    args = ap.parse_args(argv)

    if args.tope < 0:
        fracaso("--tope no puede ser negativo")
    if args.crecimiento < 0:
        fracaso("--crecimiento no puede ser negativo")

    repo, cola = separar_imagen(args.imagen)
    if not repo:
        fracaso(f"--imagen sin repo: {args.imagen!r}")
    digesto_imagen = cola if cola and DIGEST_RE.match(cola) else None
    if args.digest:
        if not DIGEST_RE.match(args.digest):
            fracaso(f"--digest no es sha256:<64 hex>: {args.digest!r}")
        if digesto_imagen and digesto_imagen != args.digest:
            fracaso(f"--digest ({args.digest}) no coincide con el de --imagen "
                    f"({digesto_imagen})")
        digesto = args.digest
    elif digesto_imagen:
        digesto = digesto_imagen
    else:
        fracaso("--imagen no lleva @digest y no se pasó --digest "
                "(el workflow lo resuelve con `crane digest`)")

    comprimido = comprimido_del_manifiesto(leer_json(args.manifest, "manifiesto"))

    baseline = leer_json(args.baseline, "baseline")
    if not isinstance(baseline, dict) or not isinstance(baseline.get("imagenes"), dict):
        fracaso("la baseline no tiene la forma canónica "
                "(`{\"imagenes\": {repo: {digest: {...}}}}`, INFRA-1296)")

    linea = baseline["imagenes"].get(repo)
    linea = linea.get(digesto) if isinstance(linea, dict) else None
    base = linea.get("comprimido") if isinstance(linea, dict) else None
    # Marcador `sin_dato` (o cualquier no-entero) dentro del campo: se trata
    # como sin línea base → se propone, no falla (documentado en el workflow).
    if not isinstance(base, int) or isinstance(base, bool):
        print(f"image-guard: OK (propuesta) — {repo}@{digesto}: "
              + propuesta(repo, digesto, comprimido))
        resumen = [f"## Image guard — {repo}", "",
                   f"- `{digesto}`: {comprimido} B comprimidos, sin línea base "
                   "(propuesta en el log; no falla)."]
    elif args.tope > 0 and comprimido > args.tope:
        print(f"::error::image-guard: {repo}@{digesto} ocupa {comprimido} B, "
              f"por encima del tope absoluto de {args.tope} B")
        resumen = [f"## Image guard — {repo}", "",
                   f"- ❌ `{digesto}`: {comprimido} B > tope {args.tope} B."]
        sys.stdout.write("\n".join(resumen) + "\n")
        escribir_resumen(resumen)
        return 1
    elif comprimido > base * (1.0 + args.crecimiento / 100.0):
        pct = (comprimido - base) / base * 100.0 if base else float("inf")
        detalle = (f"{repo}@{digesto} ocupa {comprimido} B frente a la línea "
                  f"base de {base} B: crecimiento del {pct:.1f}% sobre el "
                  f"umbral del {args.crecimiento:g}%")
        if args.modo == "bloquear":
            print(f"::error::image-guard: {detalle}")
            resumen = [f"## Image guard — {repo}", "",
                       f"- ❌ `{digesto}`: {comprimido} B vs base {base} B "
                       f"(+{pct:.1f}%, umbral {args.crecimiento:g}%, modo bloquear)."]
            sys.stdout.write("\n".join(resumen) + "\n")
            escribir_resumen(resumen)
            return 1
        print(f"::warning::image-guard: {detalle} (modo avisar)")
        resumen = [f"## Image guard — {repo}", "",
                   f"- ⚠️ `{digesto}`: {comprimido} B vs base {base} B "
                   f"(+{pct:.1f}%, umbral {args.crecimiento:g}%, modo avisar)."]
    else:
        print(f"image-guard: OK — {repo}@{digesto}: {comprimido} B comprimidos, "
              f"dentro de la línea base ({base} B, umbral "
              f"{args.crecimiento:g}%, tope "
              f"{args.tope if args.tope else 'sin tope'})")
        resumen = [f"## Image guard — {repo}", "",
                   f"- ✅ `{digesto}`: {comprimido} B vs base {base} B."]

    sys.stdout.write("\n".join(resumen) + "\n")
    escribir_resumen(resumen)
    return 0


def escribir_resumen(lineas: list[str]) -> None:
    destino = os.environ.get("GITHUB_STEP_SUMMARY")
    if destino:
        with open(destino, "a", encoding="utf-8") as f:
            f.write("\n" + "\n".join(lineas) + "\n")


if __name__ == "__main__":
    sys.exit(main())
