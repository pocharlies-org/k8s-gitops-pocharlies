#!/usr/bin/env python3
"""Self-check de scripts/pr-agent-auth-check.py (INFRA-620).

    python3 scripts/test-pr-agent-auth-check.py

Las lineas reproducen la forma real del log de PR-Agent 0.46 (JSON de loguru con
`text` y `record.level.name`, y lineas planas `| NIVEL |`), tomadas del run
37514639554 de k8s-litellm-pocharlies#229. Falla si alguien vuelve a poner el
grep ancho sobre el fichero entero.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CHECK = Path(__file__).resolve().parent / "pr-agent-auth-check.py"

# Un test del diff de #229, tal cual: es lo que el prompt de PR-Agent vuelca.
DIFF_229 = ("+    assert resp.status_code == 401\n"
            "+    assert 'Error code: 401' in str(exc)\n"
            "+    # 403 Forbidden y Bad credentials no deben degradar el gateway\n")


def registro(nivel: str, mensaje: str, exception=None) -> str:
    """Una linea JSON de loguru como las que escribe PR-Agent 0.46."""
    no = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}[nivel]
    return json.dumps({
        "text": f"{mensaje}\n",
        "record": {
            "elapsed": {"repr": "0:00:11.811090", "seconds": 11.81109},
            "exception": exception, "extra": {},
            "file": {"name": "pr_processing.py", "path": "/app/pr_agent/algo/pr_processing.py"},
            "function": "get_pr_diff",
            "level": {"icon": "x", "name": nivel, "no": no},
            "line": 168, "message": mensaje, "module": "pr_processing",
            "name": "pr_agent.algo.pr_processing",
            "process": {"id": 7, "name": "MainProcess"},
            "thread": {"id": 1, "name": "MainThread"},
            "time": {"repr": "2026-10-06 18:54:40.402+00:00", "timestamp": 1791312880.4},
        }}, ensure_ascii=False)


INFO_OK = registro("INFO", "PR main language: Python")


def auth(*lineas: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "pr-agent.log"
        log.write_text("\n".join(lineas) + "\n", encoding="utf-8")
        r = subprocess.run([sys.executable, str(CHECK), str(log)],
                           capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout.strip()


class TestAuthCheck(unittest.TestCase):
    def test_falso_positivo_debug_con_diff(self):
        # C1: el diff con `status_code == 401` en una linea DEBUG no es credencial rota
        self.assertEqual(auth(
            INFO_OK,
            registro("DEBUG", "full_prompt:\nDiff:\n" + DIFF_229),
            registro("DEBUG", "Generating prediction with openai/alibaba-q38-flash"),
        ), "auth=false")

    def test_ruido_info_con_prompt(self):
        # el extra_instructions del prompt menciona 401 Unauthorized en nivel INFO
        self.assertEqual(auth(
            registro("INFO", "extra_instructions: un 401 Unauthorized es rojo, un 429 verde"),
        ), "auth=false")

    def test_error_real_json(self):
        # C2: un ERROR de PR-Agent con el 401 del proveedor
        self.assertEqual(auth(
            INFO_OK,
            registro("ERROR", "Failed to generate prediction: litellm.AuthenticationError: "
                              "OpenAIException - Error code: 401: Unauthorized"),
        ), "auth=true")

    def test_error_real_formato_plano(self):
        self.assertEqual(auth(
            "2026-10-06 18:54:29.373 | ERROR    | pr_agent.algo.ai_handlers:chat_completion:"
            "180 - Error code: 403 - Forbidden",
        ), "auth=true")

    def test_excepcion_adjunta_a_un_registro_warning(self):
        self.assertEqual(auth(
            registro("WARNING", "Failed to review PR",
                     {"type": "AuthenticationError", "value": "Bad credentials", "traceback": True}),
        ), "auth=true")

    def test_traceback_suelto_tras_debug(self):
        self.assertEqual(auth(
            registro("DEBUG", "Generating prediction"),
            "Traceback (most recent call last):",
            "litellm.exceptions.AuthenticationError: Error code: 401",
        ), "auth=true")

    def test_plano_debug_multilinea_no_cuenta(self):
        # volcado DEBUG en formato plano: las lineas de continuacion heredan el nivel
        self.assertEqual(auth(
            "2026-10-06 18:54:29.373 | DEBUG    | pr_agent.algo.pr_processing:get_pr_diff:1 - Diff:",
            "+    assert resp.status_code == 401",
            "+    assert 'Error code: 401' in str(exc)",
        ), "auth=false")

    def test_429_y_5xx_no_son_credencial(self):
        # D3: modelo no disponible degrada a verde
        self.assertEqual(auth(
            registro("ERROR", "litellm.RateLimitError: Error code: 429"),
            registro("ERROR", "Error code: 503 Service Unavailable"),
        ), "auth=false")

    def test_workflow_no_vuelve_al_grep_ancho(self):
        # C3/C4: el reusable decide con el script, no con un grep sobre el log entero
        wf = (CHECK.parent.parent / ".github/workflows/reusable-pr-review.yml").read_text(
            encoding="utf-8")
        self.assertIn("scripts/pr-agent-auth-check.py", wf)
        self.assertNotIn("Bad credentials", wf)
        self.assertNotIn("PermissionDeniedError", wf)

    def test_log_inexistente(self):
        r = subprocess.run([sys.executable, str(CHECK), "/no/existe.log"],
                           capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "auth=false"))


if __name__ == "__main__":
    unittest.main()
