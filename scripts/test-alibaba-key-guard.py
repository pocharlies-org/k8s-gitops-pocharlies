#!/usr/bin/env python3
"""Self-check del guard de keys directas de Alibaba (DGX-625).

Se ejecuta solo, sin tocar el cluster ni ningún repo ajeno:
    python3 scripts/test-alibaba-key-guard.py

Fixture: un ExternalSecret falso con la key directa → rojo (exit 1); con el
globo en `permitidos` → verde (exit 0). Cubre además los cuatro falsos
positivos/negativos que importan: comentario, fichero de test, URL con `//`
en el protocolo, y `secretKeyRef` a un secreto que NO es `litellm-alibaba*`.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parent / "alibaba-key-guard.py"

ES_FALSO = """apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: consumidor-alibaba
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword-connect
  target:
    name: consumidor-alibaba
  data:
    - secretKey: password
      remoteRef:
        key: alibaba-model-studio/k1
"""


def correr(raiz: Path, permitidos: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GUARD), "--workdir", str(raiz),
         "--permitidos", permitidos],
        capture_output=True, text=True)


class TestGuard(unittest.TestCase):
    def fixture(self, raiz: Path) -> None:
        (raiz / "k8s" / "apps" / "consumidor").mkdir(parents=True)
        (raiz / "k8s" / "apps" / "consumidor" / "externalsecret.yaml").write_text(
            ES_FALSO, encoding="utf-8")

    def test_es_falso_rojo(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            self.fixture(raiz)
            r = correr(raiz)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("k8s/apps/consumidor/externalsecret.yaml", r.stdout)
            self.assertIn("alibaba-model-studio", r.stdout)

    def test_con_permitidos_verde(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            self.fixture(raiz)
            r = correr(raiz, "k8s/apps/consumidor/*=pendiente DGX-622")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("pendiente DGX-622", r.stdout)  # queda listado

    def test_comentario_no_cuenta(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "notas.yaml").write_text(
                "# DASHSCOPE_API_KEY: documentado aqui, no montado\n",
                encoding="utf-8")
            self.assertEqual(correr(raiz).returncode, 0)

    def test_url_no_es_comentario(self):
        # regresión: `//` dentro de https:// no es comentario
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "app.py").write_text(
                'BASE = "https://maas.aliyuncs.com/api/v1"\n', encoding="utf-8")
            self.assertEqual(correr(raiz).returncode, 1)

    def test_secret_ref_a_litellm_alibaba(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "dep.yaml").write_text(
                "env:\n  - name: K\n    valueFrom:\n      secretKeyRef:\n"
                "        name: litellm-alibaba-k1\n        key: password\n",
                encoding="utf-8")
            self.assertEqual(correr(raiz).returncode, 1)

    def test_secret_ref_a_otro_no_cuenta(self):
        # el patron 4 es SOLO a litellm-alibaba*; los secrets propios de cada
        # consumidor los cazan los otros patrones (remoteRef/env), no este
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "dep.yaml").write_text(
                "envFrom:\n  - secretRef:\n      name: consumidor-alibaba\n",
                encoding="utf-8")
            self.assertEqual(correr(raiz).returncode, 0)

    def test_ficheros_de_test_no_cuentan(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "tests").mkdir()
            (raiz / "tests" / "test_algo.py").write_text(
                'X = "DASHSCOPE_API_KEY"\n', encoding="utf-8")
            (raiz / "test_guardias.py").write_text(
                'X = "alibaba-model-studio"\n', encoding="utf-8")
            self.assertEqual(correr(raiz).returncode, 0)

    def test_arbol_limpio_verde(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "ok.yaml").write_text("kind: ConfigMap\n", encoding="utf-8")
            self.assertEqual(correr(raiz).returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
