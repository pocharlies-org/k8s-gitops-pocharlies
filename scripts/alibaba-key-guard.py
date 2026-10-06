#!/usr/bin/env python3
"""Guard de keys directas de Alibaba, estándar de la org: falla si el árbol monta una key directa fuera de `permitidos`.

DGX-625 (épica DGX-619) · 06-10-2026. Todo lo que gasta el Token Plan de
Alibaba pasa por LiteLLM / el plan-gateway; un consumidor nuevo que vuelva a
montar la key directa (item `alibaba-model-studio`, env `DASHSCOPE_API_KEY`,
host `maas.aliyuncs.com` o `secretKeyRef`/`secretRef` a los secrets
`litellm-alibaba*` del dueño) queda fuera de reparto, sin failover ni ledger.
Este guard lo impide en CI, con el patrón de `duplicados`: la lógica vive
aquí, cada repo se enciende copiando `templates/ci/alibaba-key-guard.yml`.

A diferencia de `duplicados.py` (que solo mide lo que AÑADE la PR), este guard
escanea el ÁRBOL COMPLETO: un consumidor pendiente de migrar vive ya en el
tronco, y la lista `permitidos` es el inventario declarado de esa deuda —
cada globo lleva su motivo y su historia. La pieza de cluster (Kyverno,
DGX-626) es la que cubre lo que se cree a mano; este job no toca el cluster.

Qué se ignora: ficheros de test (`test_*.py`, `tests/`, `fixtures/`...) — el
propio guard y sus fixtures citan los patrones para probarlos — y líneas en
comentario (`#`, y `//` solo si la línea empieza por él: una URL lleva `//`
en el protocolo y no es un comentario). Los bloques `/* */` y los docstrings
de Python NO se tratan como comentario: si un docstring cita el patrón, es un
hit y va a `permitidos` con su motivo (ponytail: docstring-awareness solo
cuando el ruido lo justifique).

`permitidos`: entradas separadas por comas, cada una `glob` o
`glob=motivo`. El glob se casa con la ruta relativa al `--workdir`
(fnmatch: `*` atraviesa `/`). Un hit dentro de un glob permitido se lista
como inventario pero no falla.

Salidas: 0 sin hits fuera de permitidos · 1 con hits fuera de permitidos ·
2 uso inválido (sin `--workdir` real). El informe va a stdout y, si existe,
se añade a $GITHUB_STEP_SUMMARY.

Uso:
    alibaba-key-guard.py [--workdir .] [--permitidos "glob=motivo,glob"]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from fnmatch import fnmatch
from pathlib import Path

PATRONES = (
    ("alibaba-model-studio", "item de 1Password / remoteRef de la key directa"),
    ("DASHSCOPE_API_KEY", "env que recibe la key directa"),
    ("maas.aliyuncs.com", "host directo del Model Studio"),
)
# secretKeyRef:/secretRef: -> name: litellm-alibaba* (el secreto del DUEÑO,
# usado por un consumidor). Vale la línea siguiente o el flujo inline.
SECRET_REF = re.compile(r"(secretKeyRef|secretRef):\s*(\S.*)?$")
SECRET_NAME = re.compile(r"name:\s*[\"']?(litellm-alibaba\S*)")
# Solo ficheros de texto: una key directa vive en un manifiesto, un script o
# un README, nunca dentro de un peso o una imagen (y un checkout de trabajo
# de un repo GitOps son decenas de GB de binarios que no hay ni que listar).
EXTENSIONES_TEXTO = {
    "", ".yaml", ".yml", ".py", ".sh", ".bash", ".zsh", ".js", ".ts", ".jsx",
    ".tsx", ".go", ".rb", ".php", ".tf", ".hcl", ".json", ".toml", ".ini",
    ".cfg", ".conf", ".env", ".example", ".md", ".markdown", ".txt", ".rst",
    ".html", ".css", ".sql", ".rs", ".c", ".h", ".j2", ".jinja", ".tpl",
}
# `test_*` (pytest) y `test-*` (los scripts co-locados del estilo
# scripts/test-alibaba-key-guard.py): los dos prefijos son test.
TEST_NAMES = re.compile(r"^(test[-_].*|.*_test\.\w+|conftest\.py)$")
TEST_DIRS = {"tests", "test", "fixtures", "testdata", "__pycache__", "__snapshots__"}
IGNORAR_DIRS = {".git", "node_modules", "vendor", "dist", "build",
                ".alibaba-key-guard-framework"}
MAX_BYTES = 2 * 1024 * 1024


def fracaso(mensaje: str) -> None:
    print(f"alibaba-key-guard: {mensaje}", file=sys.stderr)
    sys.exit(2)


def es_test(rel: str) -> bool:
    partes = rel.split("/")
    if TEST_NAMES.match(partes[-1]):
        return True
    return any(p in TEST_DIRS for p in partes[:-1])


def sin_comentario(linea: str) -> str:
    """La parte de la línea que no es comentario (ver docstring)."""
    if linea.lstrip().startswith("//"):
        return ""
    i = linea.find("#")
    return linea if i < 0 else linea[:i]


def parsear_permitidos(texto: str) -> list[tuple[str, str]]:
    sal = []
    for entrada in texto.split(","):
        entrada = entrada.strip()
        if not entrada:
            continue
        glob, _, motivo = entrada.partition("=")
        sal.append((glob.strip(), motivo.strip() or "(sin motivo)"))
    return sal


def escanear_archivo(rel: str, lineas: list[str]) -> list[dict]:
    hits = []
    for i, linea in enumerate(lineas):
        visible = sin_comentario(linea)
        for patron, que in PATRONES:
            if patron in visible:
                hits.append({"archivo": rel, "linea": i + 1,
                             "patron": patron, "que": que,
                             "texto": linea.strip()[:120]})
        if SECRET_REF.search(visible):
            ventana = [visible] + [sin_comentario(x) for x in lineas[i + 1:i + 5]]
            for v in ventana:
                m = SECRET_NAME.search(v)
                if m:
                    hits.append({"archivo": rel, "linea": i + 1,
                                 "patron": f"secretRef -> {m.group(1)}",
                                 "que": "referencia al secreto del dueño",
                                 "texto": linea.strip()[:120]})
                    break
    return hits


def escanear(raiz: Path) -> list[dict]:
    # scandir en vez de rglob/os.walk: un checkout de trabajo de estos repos
    # son ~800 000 ficheros (pesos, dumps); el filtro de extensión va ANTES
    # de cualquier stat y los directorios podados (.git, node_modules) ni se
    # descienden. Determinista: ordenamos por nombre a cada nivel.
    hits: list[dict] = []
    prefijo = str(raiz) + os.sep
    pila = [str(raiz)]
    while pila:
        try:
            entradas = sorted(os.scandir(pila.pop()), key=lambda e: e.name)
        except OSError:
            continue
        for e in entradas:
            if e.is_dir(follow_symlinks=False):
                # dotdirs podados salvo .github (contenido de repo): en un
                # checkout de trabajo .claude/ son transcripts de sesión que
                # citan los patrones y no son superficie del repo.
                if e.name.startswith(".") and e.name != ".github":
                    continue
                if e.name not in IGNORAR_DIRS and e.name not in TEST_DIRS:
                    pila.append(e.path)
                continue
            if os.path.splitext(e.name)[1].lower() not in EXTENSIONES_TEXTO:
                continue
            rel = e.path[len(prefijo):]
            if es_test(rel):
                continue
            try:
                if e.stat().st_size > MAX_BYTES:
                    continue
                texto = Path(e.path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue  # binario o ilegible: no es manifiesto ni código
            hits.extend(escanear_archivo(rel, texto.splitlines()))
    return hits


def informe(hits: list[dict], permitidos: list[tuple[str, str]],
            raiz: Path) -> tuple[str, int]:
    fuera, dentro = [], []
    for h in hits:
        motivo = next((m for g, m in permitidos if fnmatch(h["archivo"], g)), None)
        (dentro if motivo else fuera).append((h, motivo))
    L = ["## Alibaba key guard", "",
         f"Patrones: {', '.join(p for p, _ in PATRONES)}, "
         "`secretKeyRef`/`secretRef` -> `litellm-alibaba*` · "
         f"raiz: `{raiz}` · permitidos: {len(permitidos)} glo(s).", ""]
    if fuera:
        L.append(f"**{len(fuera)} hit(s) FUERA de permitidos** — una key de "
                 "Alibaba directa; debe pasar por LiteLLM/plan-gateway:")
        L.append("")
        for h, _ in fuera:
            L.append(f"- `{h['archivo']}:{h['linea']}` — `{h['patron']}` "
                     f"({h['que']}): `{h['texto']}`")
    else:
        L.append("**Sin keys directas fuera de permitidos.**")
    if dentro:
        L.append("")
        L.append(f"Inventario declarado en permitidos ({len(dentro)} hit(s)):")
        for h, motivo in dentro:
            L.append(f"- `{h['archivo']}:{h['linea']}` — `{h['patron']}` · {motivo}")
    return "\n".join(L) + "\n", len(fuera)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workdir", default=".", help="raiz del repo que se examina")
    ap.add_argument("--permitidos", default="",
                    help="globs separados por comas, cada uno `glob` o `glob=motivo`")
    args = ap.parse_args(argv)

    raiz = Path(args.workdir).resolve()
    if not raiz.is_dir():
        fracaso(f"{raiz} no es un directorio")

    hits = escanear(raiz)
    texto, fuera = informe(hits, parsear_permitidos(args.permitidos), raiz)
    sys.stdout.write(texto)
    resumen = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumen:
        with open(resumen, "a", encoding="utf-8") as f:
            f.write("\n" + texto)
    return 1 if fuera else 0


if __name__ == "__main__":
    sys.exit(main())
