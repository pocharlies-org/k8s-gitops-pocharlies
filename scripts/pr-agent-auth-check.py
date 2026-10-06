#!/usr/bin/env python3
"""¿El log de PR-Agent dice «credencial rota» (401/403)? (INFRA-620, regla D3)

    python3 scripts/pr-agent-auth-check.py <pr-agent.log> >> "$GITHUB_OUTPUT"

Imprime `auth=true` o `auth=false` (el paso «Run PR-Agent» lo vuelca tal cual a
su salida) y sale siempre 0. Solo cuentan los errores que PR-Agent reporta como
tales: lineas de nivel ERROR/WARNING/CRITICAL, la excepcion adjunta a un
registro, o texto suelto fuera de un registro de log (traceback de un proceso).
El volcado DEBUG/INFO del diff y del prompt NO cuenta: un PR cuyo diff contiene
`status_code == 401` no es una credencial rota.

Formatos de PR-Agent 0.46 (loguru):
  JSON   {"text": "...", "record": {"level": {"name": "ERROR"}, "message": "...",
          "exception": null | {"type": ..., "value": ...}}}
  plano  2026-10-06 18:54:29.373 | WARNING  | modulo:funcion:65 - mensaje
"""

from __future__ import annotations

import json
import re
import sys

AUTH = re.compile(
    r"AuthenticationError|PermissionDeniedError|Error code: 40[13]"
    r"|status[_ ]code[=: ]*40[13]|40[13] (Unauthorized|Forbidden)|Bad credentials")
PLANO = re.compile(r"^\d{4}-\d\d-\d\d[ T][\d:.]+\s*\|\s*([A-Z]+)\s*\|")
CUENTAN = {"ERROR", "WARNING", "CRITICAL"}
# un traceback impreso por un proceso cuenta aunque venga tras una linea DEBUG
SUELTO = re.compile(
    r"^(Traceback \(most recent call last\)|[\w.]*(AuthenticationError|PermissionDeniedError)\b)")


def textos_que_cuentan(lineas):
    nivel = None  # nivel del registro en curso; None = fuera de un registro
    for linea in lineas:
        linea = linea.rstrip("\n")
        if linea.startswith("{"):
            try:
                reg = json.loads(linea)["record"]
            except (ValueError, KeyError, TypeError):
                reg = None
            if isinstance(reg, dict):
                nivel = (reg.get("level") or {}).get("name")
                if nivel in CUENTAN:
                    yield nivel, f"{reg.get('message', '')} {reg.get('exception') or ''}"
                elif reg.get("exception"):  # excepcion adjunta, sea cual sea el nivel
                    yield nivel, str(reg["exception"])
                continue
        m = PLANO.match(linea)
        if m:
            nivel = m.group(1)
        if nivel is None or nivel in CUENTAN or SUELTO.match(linea):
            yield nivel or "SIN-NIVEL", linea


def main(ruta: str) -> bool:
    try:
        with open(ruta, encoding="utf-8", errors="replace") as f:
            for nivel, texto in textos_que_cuentan(f):
                m = AUTH.search(texto)
                if m:
                    print(f"::notice::credencial rota ({nivel}): «{m.group(0)}»", file=sys.stderr)
                    return True
    except OSError as e:  # sin log no hay prueba de credencial rota
        print(f"::warning::no se pudo leer {ruta}: {e}", file=sys.stderr)
    return False


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"uso: {sys.argv[0]} <pr-agent.log>")
    print("auth=true" if main(sys.argv[1]) else "auth=false")
