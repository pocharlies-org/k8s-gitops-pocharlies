#!/usr/bin/env python3
"""HTTP común de la pipeline de review: AuthError, Degraded y el cliente stdlib.

Lo usan los tres scripts del motor pr-agent (seguimiento D del arquitecto a
INFRA-332/INFRA-333): `review-context.py`, `review-distribute.py` y
`review-health.py`. Antes cada uno tenía su copia de la llamada y de la regla
«401/403 es credencial rechazada, lo demás es degradación»; una sola vive aquí.

Semántica fija (la misma que regía en cada script):
  - 401/403           -> AuthError(source, code). Es el único fallo que NO es
                         degradación: pone el job en rojo (exit 4).
  - 404 con ok404     -> None (borrar algo que no estaba no es un error).
  - otro 4xx/5xx, red -> Degraded(mensaje, code). El dependiente está caído o
                         contesta mal: se informa y se sigue (exit 0).
  - raw=True          -> devuelve bytes y las 3xx se siguen SIN la cabecera de
                         autorización: el zip de un artefacto vive en blob
                         storage externo y el token de GitHub no debe salir de
                         la casa. Sin raw, urlopen sigue los redirects solo.

Los tokens entran por parámetro y nunca se imprimen. Sin dependencias.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class AuthError(Exception):
    """401/403 de una API: la única falla que no es una degradación."""

    def __init__(self, source: str, code: int):
        super().__init__(f"{source} respondió HTTP {code}")
        self.source = source
        self.code = code


class Degraded(Exception):
    """Dependencia caída o respondiendo 4xx/5xx salvo 401/403; `code` es el HTTP si lo hay."""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def github_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def request(url: str, headers: dict[str, str], *, method: str | None = None,
            body: dict | None = None, raw: bool = False, ok404: bool = False,
            timeout: int = 15, source: str = "github") -> Any:
    """Una llamada HTTP: JSON (o bytes con raw), con la clasificación de errores de arriba.

    `method` por defecto: POST si hay body, GET si no. `source` es la etiqueta que
    aparece en el mensaje del error («github», «brain», «GitHub»…)."""
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Accept": "application/json", **headers}
    if data:
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs,
                                 method=method or ("POST" if data else "GET"))  # noqa: S310
    opener = urllib.request.build_opener(_NoRedirect) if raw else urllib.request.build_opener()
    try:
        with opener.open(req, timeout=timeout) as resp:  # noqa: S310
            data = resp.read()
            if raw:
                return data
            # un 204 de DELETE llega con cuerpo vacío: None, no JSONDecodeError
            return json.loads(data) if data else None
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307) and raw:
            # el zip del artefacto vive en blob storage: se sigue SIN el token
            with urllib.request.urlopen(exc.headers["Location"], timeout=timeout) as resp:  # noqa: S310
                return resp.read()
        if exc.code in (401, 403):
            raise AuthError(source, exc.code) from None
        if exc.code == 404 and ok404:
            return None
        raise Degraded(f"{source}: HTTP {exc.code}", exc.code) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise Degraded(f"{source}: {type(exc).__name__}") from None
