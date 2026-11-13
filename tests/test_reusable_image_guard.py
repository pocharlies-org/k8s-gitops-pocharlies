"""Tests de reusable-image-guard.yml: la superficie de llamada del guard (INFRA-536 C4).

Run: python3 -m unittest tests.test_reusable_image_guard
Sin red: se lee el YAML del tronco. La lógica de decisión del guard vive en
`scripts/image-guard.py` y se prueba en `tests/test_image_guard.py`; el pinchado de
`uses:` y la no interpolación de `${{ inputs. }}` en `run:` ya los exige
`scripts/check-workflow-pins.py` en CI. Lo que fija este archivo es lo que consume
quien llama al reusable y qa verificó a mano al cerrar la épica (grep de
`workflow_call` sobre el fichero del tronco):

- está declarado como `workflow_call` (C4: guard callable);
- `imagen` es la única entrada obligatoria y las actuales siguen existiendo con su
  default (la superficie es aditiva: un nombre o un default no desaparece);
- el job se llama `image-guard` (el nombre del check que ven los consumidores);
- hadolint y crane se invocan como imagen fijada por digest: `check-workflow-pins.py`
  solo alcanza los `uses:`, no los `docker run` del runner arc-k8s, que no las trae.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "reusable-image-guard.yml"
CUERPO = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
TEXTO = WORKFLOW.read_text(encoding="utf-8")
JOBS = CUERPO["jobs"]
ENTRADAS = CUERPO[True]["workflow_call"]["inputs"]


class TestEsLlamable(unittest.TestCase):
    def test_declarado_como_workflow_call(self):
        # El criterio C4: un reusable que pierde `workflow_call` deja de ser callable
        # y los consumidores fallan al usarlo. Es el grep que qa midió a mano.
        self.assertIn("workflow_call", CUERPO[True])

    def test_el_job_existe_con_nombre_de_check_estable(self):
        self.assertIn("image-guard", JOBS)
        self.assertEqual(JOBS["image-guard"]["name"], "image-guard")


class TestSuperficieDeEntradas(unittest.TestCase):
    """Las entradas actuales no cambian de nombre ni de obligatoriedad; solo se suma."""

    def test_imagen_es_la_unica_entrada_obligatoria(self):
        requeridas = [n for n, e in ENTRADAS.items() if e.get("required")]
        self.assertEqual(requeridas, ["imagen"])

    def test_entradas_actuales_intactas_con_su_default(self):
        for nombre in ("runner", "dockerfile", "baseline", "modo", "tope",
                       "crecimiento", "plataforma", "nombre", "framework_sha"):
            self.assertIn(nombre, ENTRADAS, f"entrada {nombre} eliminada o renombrada")
            self.assertFalse(ENTRADAS[nombre].get("required", False),
                             f"{nombre} pasó a ser obligatoria")
            self.assertIn("default", ENTRADAS[nombre], f"{nombre} perdió su default")

    def test_defaults_del_plan(self):
        self.assertEqual(ENTRADAS["modo"]["default"], "bloquear")
        self.assertEqual(ENTRADAS["crecimiento"]["default"], 20)
        self.assertEqual(ENTRADAS["tope"]["default"], 0)
        self.assertEqual(ENTRADAS["plataforma"]["default"], "linux/amd64")


class TestHerramientasFijadasPorDigest(unittest.TestCase):
    """`docker run` del runner arc-k8s: las dos imágenes, fijadas por digest.

    `check-workflow-pins.py` pincha los `uses:`; estos `docker run` no los alcanza
    y el runner no trae hadolint ni crane (skill ci-runners-arc).
    """

    def test_hadolint_fijada_por_digest(self):
        self.assertRegex(TEXTO, r"hadolint/hadolint@sha256:[0-9a-f]{64}")
        self.assertNotIn("hadolint/hadolint:", TEXTO)  # ningún tag mutable

    def test_crane_fijado_por_digest(self):
        self.assertRegex(TEXTO, r"go-containerregistry/crane@sha256:[0-9a-f]{64}")
        self.assertNotIn("go-containerregistry/crane:", TEXTO)


if __name__ == "__main__":
    unittest.main()
