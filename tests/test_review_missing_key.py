"""Tests for .github/actions/llm-review/review.py: sin LITELLM_CI_KEY el check
sale en ROJO, no en verde con skipping (SC-1916: el silencio era el defecto).

Run: python3 -m unittest tests/test_review_missing_key.py
stdlib only. No toca red: sin key el script termina antes de llamar a LiteLLM.
"""

from __future__ import annotations

import importlib.util
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / ".github/actions/llm-review/review.py"
spec = importlib.util.spec_from_file_location("llm_review", SCRIPT)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)

ENV_FIJAS = {
    'REVIEW_LITELLM_URL': 'http://litellm.invalid',
    'REVIEW_MODEL': 'alibaba-q38-flash',
    'REVIEW_REPO': 'pocharlies-org/un-repo',
    'REVIEW_SHA': 'deadbeef' * 5,
    'REVIEW_PR_NUMBER': '',
    'REVIEW_GITHUB_TOKEN': '',
}


class TestFaltaKey(unittest.TestCase):
    def setUp(self):
        self._antes = {k: os.environ.get(k) for k in (*ENV_FIJAS, 'REVIEW_LITELLM_KEY')}
        os.environ.update(ENV_FIJAS)
        os.environ.pop('REVIEW_LITELLM_KEY', None)
        fh = tempfile.NamedTemporaryFile('w', suffix='.diff', delete=False)
        fh.write('--- a/x\n+++ b/x\n+hola\n')
        fh.close()
        os.environ['REVIEW_DIFF_FILE'] = fh.name
        self.addCleanup(os.unlink, fh.name)

    def tearDown(self):
        for k, v in self._antes.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_sin_key_rojo(self):
        with redirect_stdout(io.StringIO()) as salida:
            rc = review.main()
        self.assertEqual(rc, 1, 'sin credencial el job debe fallar, no omitir en verde')
        self.assertIn('::error::', salida.getvalue())

    def test_con_key_no_es_el_camino_rojo(self):
        os.environ['REVIEW_LITELLM_KEY'] = 'sk-algo'
        # Con key se va a LiteLLM (host invalido): el rojo por key ausente no
        # es un rojo general. Aqui basta comprobar que no sale por la rama de
        # key ausente: el mensaje exclusivo de esa rama no aparece.
        try:
            with redirect_stdout(io.StringIO()) as salida:
                review.main()
        except Exception:  # noqa: BLE001: el fallo de red no es el asunto
            pass
        self.assertNotIn('sin LITELLM_CI_KEY', salida.getvalue())


if __name__ == '__main__':
    unittest.main()
