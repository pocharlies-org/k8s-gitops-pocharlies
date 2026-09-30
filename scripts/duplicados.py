#!/usr/bin/env python3
"""Detector de código copiado, estándar de la org: falla SOLO si la PR introduce duplicación nueva.

30-09-2026 · Dani: "que el detector de copia sea estándar de todos los repos".
Cada repo lo enciende copiando `templates/ci/duplicados.yml` (cinco líneas);
la orquestación vive en `.github/workflows/reusable-duplicados.yml` y la
lógica aquí.

Por qué solo cuenta lo nuevo: la duplicación ya existente está en el tronco y
no es culpa de esta PR. Si el check contara el inventario completo, los ~113
repos nacerían ya en rojo y nadie podría mergear nada hasta pagar una deuda
que no tocó — la forma más rápida de que un check acabado de instalar se
silencie. La pregunta que responde es una: ¿copia esta PR código que ya
existía (o se copia a sí misma entre ficheros nuevos)? Lo demás se denuncia
aparte, si algún día toca a alguien.

Cómo:
  1. jscpd (versión fijada en JSCPD_VERSION, vía `npx --yes`) escanea el árbol
     de la cabeza con `--reporters json`. `--min-tokens` se baja a 30 para que
     el criterio real sea de LÍNEAS (por defecto jscpd exige ~50 tokens y
     bloque de shell de 12 líneas se le escapan).
  2. Las líneas AÑADIDAS por la PR salen de `git diff -U0 base...head`
     (tres puntos: merge-base, o sea solo lo que aporta la rama).
  3. Un clon cuenta si al menos uno de sus fragmentos solapa líneas añadidas y
     el bloque tiene >= min_lineas líneas. Con los dos fragmentos añadidos por
     la PR, la copia es entre ficheros nuevos: también cuenta.

Formatos por defecto: código (python, javascript, typescript, jsx, tsx, go,
bash, css, html). NO yaml/json/markdown: en GitOps son repetitivos por
naturaleza y el ruido mataría la señal. Ignora siempre node_modules, vendor,
dist, build, *.min.*, lockfiles, fixtures, código generado y `.github/`.

Salidas: 0 sin duplicación nueva · 1 con duplicación nueva · 2 uso inválido o
fallo del entorno (sin node/npx, jscpd no escribe informe, SHAs inexistentes).
El informe va a stdout y, si existe, se añade a $GITHUB_STEP_SUMMARY.

Uso:
    duplicados.py --base <sha> --head <sha> [--workdir .]
                  [--min-lineas 12] [--formatos python,javascript,...]
                  [--ignorar "glob,glob"]
    # --base vacío: todo el árbol cuenta como añadido (primer commit).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# Fija: es lo único que hace reproducible un `npx --yes`. Cambiarla es un
# commit propio; sin versión, npx resolvería la última y el check mutaría solo.
JSCPD_VERSION = "5.4.0"
# 30 tokens: cualquier bloque de >= 12 líneas de código real los pasa, y deja
# el umbral de líneas como criterio único (medido: el default de jscpd ~50
# no veía un bloque shell de 14 líneas y 49 tokens).
MIN_TOKENS = "30"
FORMATOS_DEFECTO = "python,javascript,typescript,jsx,tsx,go,bash,css,html"
# jscpd no tiene formato "html": lo llama "markup" (incluye también xml).
FORMATO_JSCPD = {"html": "markup"}
IGNORAR_DEFECTO = (
    "**/node_modules/**", "**/vendor/**", "**/dist/**", "**/build/**",
    "**/*.min.*", "**/package-lock.json", "**/yarn.lock", "**/pnpm-lock.yaml",
    "**/tests/fixtures/**", "**/fixtures/**", "**/testdata/**",
    "**/*_generated.*", "**/*.generated.*", "**/gen/**",
    "**/.github/**", "**/.duplicados-framework/**",
)
ARBOL_VACIO = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def fracaso(mensaje: str) -> "None":
    print(f"duplicados: {mensaje}", file=sys.stderr)
    sys.exit(2)


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if check and r.returncode != 0:
        fracaso(f"git {' '.join(args)}: {r.stderr.strip()[:400]}")
    return r


def lineas_anadidas(repo: Path, base: str, head: str) -> dict[str, set[int]]:
    """path -> números de línea añadidos por la PR en el árbol de head.

    Con base vacía (o el árbol vacío) todo el árbol cuenta como añadido.
    """
    comunes = ["-c", "core.quotePath=false", "diff", "-U0", "--no-color"]
    if base:
        r = git(repo, *comunes, f"{base}...{head}", check=False)
        if r.returncode != 0:
            # Sin merge-base (historiales sin relación o fetch parcial): dos
            # puntos, que es el rango que el llamador pidió literalmente.
            r = git(repo, *comunes, base, head)
        diff = r.stdout
    else:
        diff = git(repo, *comunes, ARBOL_VACIO, head).stdout
    anadidas: dict[str, set[int]] = {}
    archivo: str | None = None
    for linea in diff.splitlines():
        if linea.startswith("+++ b/"):
            archivo = linea[6:]
            if archivo.startswith('"') and archivo.endswith('"'):
                archivo = archivo[1:-1]
        elif linea.startswith("+++ "):
            archivo = None  # /dev/null: fichero borrado, no añade líneas
        elif linea.startswith("@@") and archivo is not None:
            m = HUNK.match(linea)
            if not m:
                continue
            inicio = int(m.group(1))
            cuenta = int(m.group(2) if m.group(2) is not None else 1)
            if cuenta > 0:
                anadidas.setdefault(archivo, set()).update(range(inicio, inicio + cuenta))
    return anadidas


def escanear(repo: Path, formatos: list[str], ignorar: list[str],
             min_lineas: int, outdir: Path) -> list[dict]:
    """jscpd sobre el árbol de trabajo; devuelve su lista `duplicates`."""
    cmd = [
        "npx", "--yes", f"jscpd@{JSCPD_VERSION}",
        "--reporters", "json", "--output", str(outdir),
        "--min-lines", str(min_lineas), "--min-tokens", MIN_TOKENS,
        "--format", ",".join(FORMATO_JSCPD.get(f, f) for f in formatos),
        "--ignore", ",".join(ignorar),
        str(repo),
    ]
    try:
        r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=600)
    except FileNotFoundError:
        fracaso("no hay `npx` en el PATH: el runner necesita Node "
                "(en arc-k8s lo baja el propio reusable, ver reusable-duplicados.yml)")
    except subprocess.TimeoutExpired:
        fracaso("jscpd no terminó en 600 s")
    informe = outdir / "jscpd-report.json"
    if not informe.exists():
        fracaso(f"jscpd no escribió informe (exit {r.returncode}): "
                f"{(r.stderr or r.stdout).strip()[:400]}")
    try:
        return json.loads(informe.read_text(encoding="utf-8")).get("duplicates", [])
    except json.JSONDecodeError as e:
        fracaso(f"informe de jscpd ilegible: {e}")


def solapa(anadidas: dict[str, set[int]], clon: dict) -> bool:
    lineas = anadidas.get(clon["name"])
    if not lineas:
        return False
    return any(l in lineas for l in range(int(clon["start"]), int(clon["end"]) + 1))


def marcos_nuevos(duplicados: list[dict], anadidas: dict[str, set[int]],
                  min_lineas: int) -> list[dict]:
    """Clones con al menos un fragmento en líneas añadidas y >= min_lineas.

    Agrupa por fragmento nuevo: si la copia se repite contra tres originales,
    una línea del informe con tres destinos.
    """
    agrupado: dict[tuple, dict] = {}
    for dup in duplicados:
        lineas = int(dup.get("lines") or 0)
        if lineas < min_lineas:
            continue
        a, b = dup["firstFile"], dup["secondFile"]
        na, nb = solapa(anadidas, a), solapa(anadidas, b)
        if not (na or nb):
            continue
        nuevo, original = (a, b) if na else (b, a)
        clave = (nuevo["name"], int(nuevo["start"]), int(nuevo["end"]), na and nb)
        entrada = agrupado.setdefault(
            clave, {"lineas": lineas, "ambos": bool(na and nb), "originales": []})
        destino = (original["name"], int(original["start"]), int(original["end"]))
        if destino != clave[:3] and destino not in entrada["originales"]:
            entrada["originales"].append(destino)
    return [
        {"nuevo": clave[:3], "ambos": clave[3], **e}
        for clave, e in agrupado.items()
    ]


def informe(marcos: list[dict], total_clones: int, min_lineas: int,
            formatos: list[str]) -> str:
    L = [f"## Duplicados · jscpd {JSCPD_VERSION}", ""]
    L.append(f"Umbral: >= {min_lineas} líneas · formatos: {', '.join(formatos)} · "
             f"clones en el árbol: {total_clones} (los ya existentes en el tronco "
             "no cuentan: este check solo mide lo que añade esta PR).")
    L.append("")
    if not marcos:
        L.append("**Sin duplicación nueva.**")
        return "\n".join(L) + "\n"
    L.append(f"**{len(marcos)} fragmento(s) nuevo(s) copiado(s) por esta PR:**")
    L.append("")
    L.append("| # | Líneas | Fragmento nuevo | Dónde está el original |")
    L.append("|---|--------|-----------------|------------------------|")
    for i, m in enumerate(marcos, 1):
        n = m["nuevo"]
        nuevo = f"`{n[0]}:{n[1]}-{n[2]}`"
        originales = "<br>".join(f"`{o[0]}:{o[1]}-{o[2]}`" for o in m["originales"]) or "—"
        if m["ambos"]:
            originales += " (también nuevo en esta PR)"
        L.append(f"| {i} | {m['lineas']} | {nuevo} | {originales} |")
    L.append("")
    L.append("Mover código de sitio no es duplicarlo: si el bloque viejo sigue "
             "ahí por error, borra el original o saca la copia a una función "
             "compartida.")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="", help="SHA base (vacío: todo el árbol es nuevo)")
    ap.add_argument("--head", required=True, help="SHA cabeza del diff")
    ap.add_argument("--workdir", default=".", help="Raiz del repo git que se examina")
    ap.add_argument("--min-lineas", type=int, default=12)
    ap.add_argument("--formatos", default=FORMATOS_DEFECTO,
                    help="lista separada por comas (nombres de usuario; html -> markup)")
    ap.add_argument("--ignorar", default="",
                    help="globs extra separados por comas (se suman a los de la casa)")
    args = ap.parse_args(argv)

    if args.min_lineas < 1:
        fracaso("--min-lineas tiene que ser >= 1")
    repo = Path(args.workdir).resolve()
    if not (repo / ".git").exists():
        fracaso(f"{repo} no es un repo git")
    git(repo, "rev-parse", "--git-dir")
    for s in (args.base, args.head):
        if s and git(repo, "cat-file", "-e", f"{s}^{{commit}}", check=False).returncode != 0:
            fracaso(f"el objeto {s} no existe en el repo (¿falta fetch?)")

    # Vacio = defectos de la casa: el reusable pasa los inputs siempre, y no
    # queremos un `--format ""` en jscpd.
    formatos = [f.strip() for f in args.formatos.split(",") if f.strip()] or \
        [f.strip() for f in FORMATOS_DEFECTO.split(",")]
    anadidas = lineas_anadidas(repo, args.base, args.head)
    marcos: list[dict] = []
    if not any(anadidas.values()):
        # PR sin líneas añadidas (o solo borrados): no puede introducir copia.
        print("duplicados: la PR no añade líneas; nada que comparar.")
        texto = informe([], 0, args.min_lineas, formatos)
    else:
        ignorar = list(IGNORAR_DEFECTO) + [g.strip() for g in args.ignorar.split(",") if g.strip()]
        with tempfile.TemporaryDirectory(prefix="jscpd-",
                                         dir=os.environ.get("RUNNER_TEMP") or None) as tmp:
            duplicados = escanear(repo, formatos, ignorar, args.min_lineas, Path(tmp))
        marcos = marcos_nuevos(duplicados, anadidas, args.min_lineas)
        texto = informe(marcos, len(duplicados), args.min_lineas, formatos)
        if duplicados and not marcos:
            print("duplicados: hay duplicación en el árbol, pero ninguna toca "
                  "líneas añadidas por esta PR.")

    sys.stdout.write(texto)
    resumen = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumen:
        with open(resumen, "a", encoding="utf-8") as f:
            f.write("\n" + texto)
    return 1 if marcos else 0


if __name__ == "__main__":
    sys.exit(main())
