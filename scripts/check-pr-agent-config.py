#!/usr/bin/env python3
"""Valida .pr_agent.toml antes de que lo cargue PR-Agent (INFRA-298 / INFRA-331).

PR-Agent 0.46.0 no revienta con una configuración mala: su cargador (custom_merge_loader,
silent=True) salta el fichero entero si el TOML no parsea, e ignora sin avisar una clave mal
escrita. El job arranca entonces con los valores por defecto de PR-Agent: auto_describe
encendido, restricted_mode apagado y el modelo gpt-5.6. Este script falla antes, en el CI.

Comprueba, solo con la biblioteca estándar:
  1. que el fichero parsea (tomllib);
  2. las decisiones de la épica que no pueden derivar (D4 modelo, D5 auto_describe apagado,
     decisión 5 auto_review y auto_improve encendidos, restricted_mode, allowlist de proyectos
     de Jira, sin fallback);
  3. que no lleva credenciales ni endpoints (llegan por entorno desde el workflow);
  4. con --upstream: que cada [sección] y clave existe en el configuration.toml de la versión
     de PR-Agent fijada (incluidas las documentadas en comentario, como jira_site o
     github_action_config.auto_describe). Una errata deja de ser silenciosa.

Uso:
  python3 scripts/check-pr-agent-config.py [--config .pr_agent.toml] [--upstream configuration.toml]
Salida: 0 válido · 1 inválido (un fallo por línea) · 2 uso inválido (fichero ausente).
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

MODEL = "openai/alibaba-q38-flash"
PROJECT_KEYS = {"SC", "INFRA", "DGX", "SKIRM", "OWU"}

# (sección, clave) -> valor exigido. Solo decisiones, no ajustes finos: el tamaño de ventana
# o el timeout se cambian en el .toml sin tocar este script.
REQUIRED = {
    ("config", "git_provider"): "github",
    ("config", "model"): MODEL,
    ("config", "fallback_models"): [],
    ("config", "restricted_mode"): True,
    ("github_action_config", "auto_describe"): False,
    # Decisión 5 del CTO: /improve está encendido y no toca título ni cuerpo. (F0 §5 decía que
    # el inline solo salía por /improve; medido sobre la fuente fijada, /review publica inline
    # con pr_reviewer.inline_key_issues — criterio 1, rework qa de INFRA-332.)
    ("github_action_config", "auto_review"): True,
    ("github_action_config", "auto_improve"): True,
    # Criterio 1 (INFRA-332): intención de inline en /review. En 0.46.0 es inerte en GitHub
    # (el provider no implementa la verificación; run 36879060762) — el inline real sale por
    # sugerencias con suggestions_score_threshold abajo.
    ("pr_reviewer", "inline_key_issues"): True,
    # Criterio 1 (INFRA-332, rework 2): con el default (1), self_reflect puntúa la sugerencia
    # de contrato con 0 y se descarta antes de publicar → pulls/N/comments vacío (medido en
    # #187 y #194). 0 = se publican todas, incluida la de contrato, en su línea.
    ("pr_code_suggestions", "suggestions_score_threshold"): 0,
    # Una sola etiqueta de seguridad (INFRA-298 comentario 17496): la de pr-watcher, no la de PR-Agent.
    ("pr_reviewer", "enable_review_labels_security"): False,
}
POSITIVE_INTS = [("config", "max_model_tokens"), ("config", "custom_model_max_tokens"),
                 ("config", "ai_timeout")]
# Credenciales y destinos: nunca en el fichero (va a un repo público y a la config de host).
FORBIDDEN_KEY = re.compile(r"(^|_)(key|token|password|secret|api_email|api_base|base_url|url)$", re.I)

SECTION_RE = re.compile(r"^\s*#?\s*\[([A-Za-z0-9_.-]+)\]")
KEY_RE = re.compile(r"^\s*#?\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")


def upstream_keys(path: Path) -> dict[str, set[str]]:
    """Secciones y claves del configuration.toml upstream, también las que van comentadas."""
    keys: dict[str, set[str]] = {}
    section = None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = SECTION_RE.match(line)
        if m and not KEY_RE.match(line):
            section = m.group(1).lower()
            keys.setdefault(section, set())
            continue
        m = KEY_RE.match(line)
        if m and section is not None:
            keys[section].add(m.group(1).lower())
    return keys


def check(data: dict, upstream: dict[str, set[str]] | None) -> list[str]:
    errors: list[str] = []

    def get(section: str, key: str):
        return data.get(section, {}).get(key, None) if isinstance(data.get(section), dict) else None

    for (section, key), want in REQUIRED.items():
        got = get(section, key)
        if got != want:
            errors.append(f"{section}.{key} = {got!r}; se exige {want!r}")

    for section, key in POSITIVE_INTS:
        got = get(section, key)
        if not isinstance(got, int) or isinstance(got, bool) or got <= 0:
            errors.append(f"{section}.{key} = {got!r}; se exige un entero > 0")

    keys = get("jira", "project_keys")
    if not isinstance(keys, list) or set(keys) != PROJECT_KEYS or len(keys) != len(PROJECT_KEYS):
        errors.append(f"jira.project_keys = {keys!r}; se exige exactamente {sorted(PROJECT_KEYS)}")

    effort = get("config", "reasoning_effort")
    if effort is not None and MODEL not in (get("config", "additional_reasoning_effort_models") or []):
        errors.append(f"config.reasoning_effort = {effort!r} sin {MODEL!r} en "
                      "config.additional_reasoning_effort_models: PR-Agent lo descarta en silencio")

    for section, table in data.items():
        if not isinstance(table, dict):
            errors.append(f"{section}: clave suelta fuera de una [sección]")
            continue
        for key, value in table.items():
            if isinstance(value, dict):
                errors.append(f"{section}.{key}: tabla anidada; PR-Agent solo lee [sección] clave = valor")
            if FORBIDDEN_KEY.search(key):
                errors.append(f"{section}.{key}: credencial o endpoint en el fichero; va por entorno")
            if upstream is not None:
                if section.lower() not in upstream:
                    errors.append(f"[{section}]: sección desconocida en la versión fijada de PR-Agent")
                    break
                if key.lower() not in upstream[section.lower()]:
                    errors.append(f"{section}.{key}: clave desconocida en la versión fijada de PR-Agent")
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", default=".pr_agent.toml", type=Path)
    ap.add_argument("--upstream", type=Path,
                    help="pr_agent/settings/configuration.toml de la versión fijada")
    args = ap.parse_args(argv)

    for p in (args.config, args.upstream):
        if p is not None and not p.is_file():
            print(f"uso: no existe {p}", file=sys.stderr)
            return 2
    try:
        data = tomllib.loads(args.config.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        print(f"FALLO {args.config}: TOML inválido: {e}")
        return 1

    errors = check(data, upstream_keys(args.upstream) if args.upstream else None)
    for e in errors:
        print(f"FALLO {args.config}: {e}")
    if errors:
        return 1
    scope = "decisiones + claves upstream" if args.upstream else "decisiones (sin --upstream)"
    print(f"OK {args.config}: {sum(len(t) for t in data.values())} claves en "
          f"{len(data)} secciones · {scope}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
