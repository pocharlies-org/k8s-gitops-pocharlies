"""Tests for scripts/duplicados.py: solo la duplicacion NUEVA de la PR falla.

Run: python3 -m unittest tests/test_duplicados.py

El script llama a jscpd por `npx` (version fijada en el propio script): sin
node en el PATH la suite se salta entera; el CI del framework (ci.yml, job
`release-contract`) instala el Node verificado antes de correrla. El repo es
un git temporal real, no un fixture: lo que se prueba es el cruce entre el
informe de jscpd y las lineas anadidas por `git diff -U0 base...head`, y para
eso hace falta el detector de verdad.

Cada caso negativo (pasa) lleva su prueba de no-vacuidad: el mismo arbol con
la base en el arbol vacio SI debe fallar, para que "pasa" signifique "el
filtro de lineas anadidas hizo su trabajo", no "jscpd no vio nada".
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "duplicados.py"

# 13 lineas, denso en tokens: por encima del umbral por defecto (12).
BLOQUE = """def resumen_pedido(lineas, cliente, divisa):
    total = 0
    impuestos = 0
    descuento = descuento_de(cliente)
    for linea in lineas:
        subtotal = linea.precio * linea.cantidad
        total += subtotal
        impuestos += subtotal * linea.iva
    neto = total - descuento
    bruto = neto + impuestos
    importe = redondear(bruto, divisa)
    entrega = etiqueta(neto, divisa)
    return Envoltura(neto, bruto, importe, entrega)
"""

# 7 lineas: copia real pero por debajo del umbral de 12.
BLOQUE_PEQUENO = """def suma_acumulada(a, b, c, d):
    x = a * 3 + b
    y = c * 4 + d
    z = x + y
    w = z * 2 - x
    return x, y, z, w
"""

RELLENO = """def otro_cos_distinto(valor):
    acumulado = []
    for i in range(valor):
        if i % 2 == 0:
            acumulado.append(i * i)
        else:
            acumulado.append(i + valor)
    return sum(acumulado) / max(len(acumulado), 1)
"""


def sh(cwd: Path, *cmd: str) -> None:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    assert r.returncode == 0, f"{cmd}: {r.stdout}{r.stderr}"


class DuplicadosTest(unittest.TestCase):
    def setUp(self) -> None:
        if shutil.which("npx") is None:
            self.skipTest("no hay npx en el PATH (el runner necesita Node)")
        self.tmp = Path(tempfile.mkdtemp(prefix="duplicados-test-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        sh(self.repo, "git", "init", "-q", "-b", "main")
        sh(self.repo, "git", "config", "core.hooksPath", "/dev/null")
        sh(self.repo, "git", "config", "user.email", "t@t")
        sh(self.repo, "git", "config", "user.name", "T")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def commit(self, files: dict[str, str], msg: str) -> str:
        for rel, contenido in files.items():
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(contenido, encoding="utf-8")
        sh(self.repo, "git", "add", "-A")
        sh(self.repo, "git", "commit", "-qm", msg)
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo,
                              capture_output=True, text=True).stdout.strip()

    def run_script(self, base: str, head: str, *extra: str,
                   resumen: Path | None = None) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_STEP_SUMMARY"}
        if resumen is not None:
            env["GITHUB_STEP_SUMMARY"] = str(resumen)
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--base", base, "--head", head,
             "--workdir", str(self.repo), *extra],
            capture_output=True, text=True, env=env, cwd=self.repo)

    def test_duplicacion_nueva_falla_y_deja_informe(self) -> None:
        base = self.commit({"origen.py": BLOQUE}, "base: original")
        head = self.commit({"copia/nuevo.py": BLOQUE}, "head: la PR copia el bloque")
        resumen = self.tmp / "step-summary.md"
        r = self.run_script(base, head, resumen=resumen)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("`copia/nuevo.py:1-13`", r.stdout)
        self.assertIn("`origen.py:1-13`", r.stdout)
        texto = resumen.read_text(encoding="utf-8")
        self.assertIn("Duplicados", texto)
        self.assertIn("copia/nuevo.py", texto)
        self.assertIn("Dónde está el original", texto)

    def test_duplicacion_antigua_intacta_pasa(self) -> None:
        base = self.commit({"a.py": BLOQUE, "b.py": BLOQUE}, "base: ya duplicado")
        head = self.commit({"c.py": RELLENO}, "head: fichero nuevo sin copiar")
        r = self.run_script(base, head)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Sin duplicación nueva", r.stdout)
        # No vacuidad: el mismo arbol declarando TODO como anadido (base =
        # arbol vacio, modo primer commit) SI pinta la duplicacion.
        r_todo = self.run_script("", head)
        self.assertEqual(r_todo.returncode, 1, r_todo.stdout + r_todo.stderr)

    def test_bajo_umbral_pasa_y_el_umbral_manda(self) -> None:
        base = self.commit({"a.py": BLOQUE_PEQUENO}, "base: bloque de 7 lineas")
        head = self.commit({"b.py": BLOQUE_PEQUENO}, "head: copia pequena")
        r = self.run_script(base, head)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # Con el umbral bajado a 4 la MISMA copia si cuenta: lo que salvo el
        # anterior no fue el detector, fue min_lineas.
        r4 = self.run_script(base, head, "--min-lineas", "4")
        self.assertEqual(r4.returncode, 1, r4.stdout + r4.stderr)

    def test_ficheros_ignorados_no_cuentan(self) -> None:
        base = self.commit({"origen.py": BLOQUE}, "base: original")
        head = self.commit({"tests/fixtures/copia.py": BLOQUE}, "head: copia en fixture")
        r = self.run_script(base, head)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # Globs extra del llamador (`ignorar`): una copia en una ruta propia
        # cuenta, e ignorarla a mano la deja fuera.
        head2 = self.commit({"copias/otro.py": BLOQUE}, "head: copia en copias/")
        r2 = self.run_script(base, head2, "--ignorar", "**/copias/**")
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        # No vacuidad: sin ese glob extra, la misma PR si falla.
        r3 = self.run_script(base, head2)
        self.assertEqual(r3.returncode, 1, r3.stdout + r3.stderr)

    def test_copia_entre_dos_ficheros_nuevos_falla(self) -> None:
        self.commit({"README.md": "# repo\n"}, "base: vacio de codigo")
        head = self.commit({"x.py": BLOQUE, "y.py": BLOQUE}, "head: dos ficheros nuevos iguales")
        base = subprocess.run(["git", "rev-parse", "HEAD~1"], cwd=self.repo,
                              capture_output=True, text=True).stdout.strip()
        r = self.run_script(base, head)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("también nuevo", r.stdout)

    def test_sin_lineas_anadidas_pasa_sin_escanear(self) -> None:
        base = self.commit({"a.py": BLOQUE}, "base")
        # Borrar no anade lineas: no puede introducir copia.
        sh(self.repo, "git", "rm", "-q", "a.py")
        sh(self.repo, "git", "commit", "-qm", "head: solo borrado")
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo,
                              capture_output=True, text=True).stdout.strip()
        r = self.run_script(base, head)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("no añade líneas", r.stdout)


if __name__ == "__main__":
    unittest.main()
