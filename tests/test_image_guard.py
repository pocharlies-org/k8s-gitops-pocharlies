"""Tests de scripts/image-guard.py (INFRA-1298, épica INFRA-536 C4).

La lógica de tamaño del guard vive en el script (patrón de `duplicados.py` y
`alibaba-key-guard.py`: workflow fino, lógica y test aquí). Se ejercita por
subprocess, como `scripts/test-alibaba-key-guard.py`: lo que se prueba es el
contrato de salidas (0 pasa/avisa/propone · 1 falla · 2 uso inválido) y las
ramas del spec:

- tope absoluto → falla en AMBOS modos (es un techo duro, no crecimiento);
- crecimiento sobre el umbral → falla en modo `bloquear`, check de aviso
  (`::warning::`, exit 0) en modo `avisar`;
- imagen sin línea base → propone la entrada en el log, NO falla;
- entrada de la baseline con `comprimido: {"sin_dato": ...}` → se trata como
  sin línea base (la propone, no falla): el no-dato del inventario (P1) no
  puede poner en rojo a una imagen sana.

El manifiesto es la salida de `crane manifest --platform` (suma de
`layers[].size` = comprimido, mismo método que el inventario de INFRA-1296).

Run: python3 -m unittest tests/test_image_guard.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / "scripts" / "image-guard.py"

REPO = "harbor.e-dani.com/homelab/demo"
DIGEST = "sha256:" + "ab" * 32  # 64 hex, formato real de digest

# Manifiesto de 2 capas: 3 000 000 + 800 000 = 3 800 000 comprimidos.
MANIFIESTO = {
    "schemaVersion": 2,
    "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
    "layers": [
        {"mediaType": "application/vnd.oci.image.layer.v1.tar+gzip", "size": 3_000_000},
        {"mediaType": "application/vnd.oci.image.layer.v1.tar+gzip", "size": 800_000},
    ],
}


def baseline(entrada: dict | None) -> dict:
    """sizes-baseline.json con la forma canónica de `docs/images/` (P1)."""
    imagenes = {}
    if entrada is not None:
        imagenes[REPO] = {DIGEST: entrada}
    return {"formato": "linea base del guard (fixture)", "imagenes": imagenes}


def correr(raiz: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GUARD), *args],
        capture_output=True, text=True, cwd=raiz)


class TestImageGuard(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self._tmp.name)
        self.manifiesto = self.raiz / "manifest.json"
        self.manifiesto.write_text(json.dumps(MANIFIESTO), encoding="utf-8")
        self.baseline_path = self.raiz / "sizes-baseline.json"

    def tearDown(self):
        self._tmp.cleanup()

    def escribir_baseline(self, entrada: dict | None) -> None:
        self.baseline_path.write_text(
            json.dumps(baseline(entrada)), encoding="utf-8")

    def base(self, *args: str) -> subprocess.CompletedProcess:
        return correr(
            self.raiz,
            "--imagen", f"{REPO}@{DIGEST}",
            "--manifest", str(self.manifiesto),
            "--baseline", str(self.baseline_path),
            *args)

    # --- rama: dentro de la línea base -------------------------------------
    def test_dentro_de_linea_base_pasa(self):
        # 3 800 000 <= 3 500 000 * 1.2 = 4 200 000 → pasa.
        self.escribir_baseline({"comprimido": 3_500_000, "descomprimido": 9_000_000})
        r = self.base("--modo", "bloquear", "--crecimiento", "20")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("::warning::", r.stdout + r.stderr)

    def test_crecimiento_exacto_del_umbral_no_falla(self):
        # Umbral estricto (>): 4 200 000 == 3 500 000 * 1.2 → no es crecimiento.
        self.escribir_baseline({"comprimido": 3_500_000, "descomprimido": 1})
        r = self.base("--modo", "bloquear", "--crecimiento", "20")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    # --- rama: tope absoluto ------------------------------------------------
    def test_tope_absoluto_falla_en_bloquear(self):
        self.escribir_baseline({"comprimido": 3_500_000, "descomprimido": 1})
        r = self.base("--modo", "bloquear", "--tope", "1000000")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("tope", (r.stdout + r.stderr).lower())

    def test_tope_absoluto_falla_tambien_en_avisar(self):
        # El tope es un techo duro: `avisar` suaviza el crecimiento, no el tope.
        self.escribir_baseline({"comprimido": 3_500_000, "descomprimido": 1})
        r = self.base("--modo", "avisar", "--tope", "1000000")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_tope_cero_desactiva_el_tope(self):
        self.escribir_baseline({"comprimido": 3_500_000, "descomprimido": 1})
        r = self.base("--modo", "bloquear", "--tope", "0", "--crecimiento", "200")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    # --- rama: crecimiento sobre la línea base ------------------------------
    def test_crecimiento_falla_en_bloquear(self):
        # 3 800 000 > 3 000 000 * 1.1 = 3 300 000 → rojo en modo bloquear.
        self.escribir_baseline({"comprimido": 3_000_000, "descomprimido": 1})
        r = self.base("--modo", "bloquear", "--crecimiento", "10")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("crecimiento", (r.stdout + r.stderr).lower())

    def test_crecimiento_avisa_en_avisar(self):
        # Mismo caso: en modo avisar el check pasa con un ::warning::.
        self.escribir_baseline({"comprimido": 3_000_000, "descomprimido": 1})
        r = self.base("--modo", "avisar", "--crecimiento", "10")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("::warning::", r.stdout + r.stderr)
        self.assertIn("crecimiento", (r.stdout + r.stderr).lower())

    # --- rama: sin línea base (y marcador sin_dato) -------------------------
    def test_sin_linea_base_propone_y_no_falla(self):
        self.escribir_baseline(None)  # repo ausente de la baseline
        r = self.base("--modo", "bloquear")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(REPO, r.stdout)
        self.assertIn(DIGEST, r.stdout)
        # La propuesta es la entrada tal cual iría en sizes-baseline.json.
        self.assertIn("3800000", r.stdout)

    def test_sin_dato_en_comprimido_se_trata_como_sin_linea_base(self):
        # Documentado en el workflow: marcador sin_dato → se propone, no falla.
        self.escribir_baseline({"comprimido": {"sin_dato": "crane export timeout"},
                               "descomprimido": {"sin_dato": "omitido"}})
        r = self.base("--modo", "bloquear")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(DIGEST, r.stdout)
        self.assertIn("3800000", r.stdout)
        self.assertNotIn("::error::", r.stdout + r.stderr)

    # --- rama: uso inválido --------------------------------------------------
    def test_imagen_sin_digest_y_sin_flag_falla(self):
        self.escribir_baseline({"comprimido": 3_500_000, "descomprimido": 1})
        r = correr(
            self.raiz,
            "--imagen", f"{REPO}:latest",
            "--manifest", str(self.manifiesto),
            "--baseline", str(self.baseline_path))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_digest_incompatibles_falla(self):
        # --digest dado y el del @digest de la imagen no coinciden → uso inválido.
        self.escribir_baseline({"comprimido": 3_500_000, "descomprimido": 1})
        r = correr(
            self.raiz,
            "--imagen", f"{REPO}@{DIGEST}",
            "--digest", "sha256:" + "cd" * 32,
            "--manifest", str(self.manifiesto),
            "--baseline", str(self.baseline_path))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_manifest_sin_capas_falla(self):
        self.escribir_baseline({"comprimido": 3_500_000, "descomprimido": 1})
        vacio = self.raiz / "vacio.json"
        vacio.write_text(json.dumps({"schemaVersion": 2}), encoding="utf-8")
        r = correr(
            self.raiz,
            "--imagen", f"{REPO}@{DIGEST}",
            "--manifest", str(vacio),
            "--baseline", str(self.baseline_path))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_baseline_no_json_falla(self):
        self.baseline_path.write_text("no es json", encoding="utf-8")
        r = self.base("--modo", "bloquear")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_modo_invalido_falla(self):
        self.escribir_baseline({"comprimido": 3_500_000, "descomprimido": 1})
        r = self.base("--modo", "destruir")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    # --- formato de la entrada de imagen -------------------------------------
    def test_digest_se_extrae_del_imagen_con_arroba(self):
        # Sin --digest: el digesto vive en `repo@sha256:...` y vale.
        self.escribir_baseline({"comprimido": 3_500_000, "descomprimido": 1})
        r = self.base("--modo", "bloquear", "--crecimiento", "20")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_digest_por_flag_con_imagen_con_tag(self):
        # `crane digest` del workflow resuelve el tag: el script lo recibe por --digest.
        self.escribir_baseline({"comprimido": 3_500_000, "descomprimido": 1})
        r = correr(
            self.raiz,
            "--imagen", f"{REPO}:v1",
            "--digest", DIGEST,
            "--manifest", str(self.manifiesto),
            "--baseline", str(self.baseline_path),
            "--modo", "bloquear", "--crecimiento", "20")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
