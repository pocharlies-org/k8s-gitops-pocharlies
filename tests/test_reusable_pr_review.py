"""Tests de reusable-pr-review.yml: un solo motor por evento (SC-2182, criterio C3 c).

Run: python3 -m unittest tests.test_reusable_pr_review
Sin red: se lee el YAML y se evalua el `if:` de cada job con un evaluador de juguete (solo
`github.event_name`, `inputs.engine`, `&&`, `||`, `==`, `!=`, `!`), el unico vocabulario que
usan los jobs de motor. Un `if:` que use algo mas hace fallar la prueba, no la salta.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/reusable-pr-review.yml"
CUERPO = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
JOBS = CUERPO["jobs"]
# los jobs que SON un motor (o su validacion); `avisar` solo notifica el resultado de uno de ellos
MOTORES = ("revisar_pr", "revisar_pr_agent", "revisar_pr_juez", "revisar_commit", "evaluar_juez",
           "motor_invalido")


def corre(job: str, evento: str, engine: str) -> bool:
    expr = str(JOBS[job].get("if", "true")).strip()
    expr = re.sub(r"^\$\{\{\s*|\s*\}\}$", "", expr).strip()
    if re.search(r"[A-Za-z_.]+\(", expr):
        raise AssertionError(f"{job}: el if usa una funcion que este test no evalua: {expr}")
    py = (expr.replace("github.event_name", repr(evento)).replace("inputs.engine", repr(engine))
          .replace("&&", " and ").replace("||", " or "))
    py = re.sub(r"!(?!=)", " not ", py)
    if re.search(r"[A-Za-z_]+\.[A-Za-z_]+", re.sub(r"'[^']*'", "", py)):
        raise AssertionError(f"{job}: el if usa contexto que este test no evalua: {expr}")
    return bool(eval(py, {"__builtins__": {}}))  # noqa: S307 - expresion del propio repo, ya saneada


def en_marcha(evento: str, engine: str) -> list[str]:
    return [j for j in MOTORES if j in JOBS and corre(j, evento, engine)]


class TestUnSoloMotor(unittest.TestCase):
    def test_los_motores_existen(self):
        for j in ("revisar_pr", "revisar_pr_agent", "revisar_pr_juez", "revisar_commit"):
            self.assertIn(j, JOBS)

    def test_un_solo_motor_en_un_pull_request(self):
        for engine, esperado in (("propio", "revisar_pr"), ("pr-agent", "revisar_pr_agent"),
                                 ("juez", "revisar_pr_juez")):
            with self.subTest(engine):
                self.assertEqual(en_marcha("pull_request", engine), [esperado])

    def test_un_solo_motor_en_workflow_dispatch(self):
        self.assertEqual(en_marcha("workflow_dispatch", "propio"), ["revisar_commit"])
        self.assertEqual(en_marcha("workflow_dispatch", "juez"), ["evaluar_juez"])
        self.assertEqual(en_marcha("workflow_dispatch", "pr-agent"), [])

    def test_un_solo_motor_desconocido_es_rojo_y_no_un_silencio_verde(self):
        # antes, `revisar_pr` (engine != 'pr-agent') lo cazaba y salia en rojo (uso invalido, D6).
        for evento in ("pull_request", "workflow_dispatch"):
            self.assertEqual(en_marcha(evento, "otro"), ["motor_invalido"])
        pasos = JOBS["motor_invalido"]["steps"]
        self.assertTrue(any("exit 2" in str(p.get("run", "")) for p in pasos))

    def test_el_job_del_juez_solo_corre_en_pull_request(self):
        for engine in ("propio", "pr-agent", "juez", "otro"):
            self.assertFalse(corre("revisar_pr_juez", "workflow_dispatch", engine))
        self.assertFalse(corre("revisar_pr_juez", "pull_request", "propio"))

    def test_revisar_pr_y_revisar_commit_son_solo_del_motor_propio(self):
        for job in ("revisar_pr", "revisar_commit"):
            self.assertIn("inputs.engine == 'propio'", str(JOBS[job]["if"]))

    def test_el_nombre_del_check_del_juez(self):
        self.assertEqual(JOBS["revisar_pr_juez"]["name"], "Review del PR (juez)")


class TestSuperficieEstable(unittest.TestCase):
    """El nombre del check `<job> / <job>` y los inputs actuales no cambian; solo se suma."""

    def test_nombres_de_los_checks_de_siempre(self):
        self.assertEqual(JOBS["revisar_pr"]["name"], "Review del PR")
        self.assertEqual(JOBS["revisar_pr_agent"]["name"], "Review del PR (PR-Agent)")
        self.assertEqual(JOBS["revisar_commit"]["name"], "Review del ultimo commit")

    def test_inputs_actuales_intactos_y_fallback_model_aditivo(self):
        entradas = CUERPO[True]["workflow_call"]["inputs"]
        for nombre in ("engine", "runner", "model", "litellm_url", "max_diff_bytes", "telegram_topic",
                       "telegram_thread_id", "notificar"):
            self.assertIn(nombre, entradas)
        self.assertEqual(entradas["fallback_model"]["default"], "alibaba-q38-flash")
        self.assertEqual(entradas["fallback_model"]["type"], "string")
        # `model` es el de `propio` y no cambia; el juez tiene el suyo, aditivo (SC-2182)
        self.assertEqual(entradas["model"]["default"], "alibaba-q38-flash")
        self.assertEqual(entradas["juez_model"]["default"], "tooling")
        self.assertEqual(entradas["juez_model"]["type"], "string")

    def test_el_motor_nace_opt_in(self):
        # el cambio de default es otra PR (etapa c, con la lista medida cubierta)
        self.assertEqual(CUERPO[True]["workflow_call"]["inputs"]["engine"]["default"], "propio")

    def test_los_secretos_propios_del_juez_son_opcionales_y_los_de_siempre_siguen(self):
        secretos = CUERPO[True]["workflow_call"]["secrets"]
        for nombre in ("LITELLM_JUEZ_KEY", "JIRA_JUEZ_EMAIL", "JIRA_JUEZ_TOKEN", "JIRA_JUEZ_URL"):
            self.assertIn(nombre, secretos)
            self.assertFalse(secretos[nombre]["required"], nombre)
        for nombre in ("LITELLM_CI_KEY", "JIRA_EMAIL", "JIRA_API_TOKEN"):   # propio y pr-agent
            self.assertIn(nombre, secretos)

    def test_los_outputs_del_reusable_incluyen_el_juez(self):
        salidas = CUERPO[True]["workflow_call"]["outputs"]
        for nombre in ("veredicto", "n_hallazgos"):
            self.assertIn("revisar_pr_juez", salidas[nombre]["value"])


class TestJuezAislado(unittest.TestCase):
    def setUp(self):
        self.job = JOBS["revisar_pr_juez"]

    def test_permisos_minimos_los_mismos_que_el_motor_propio(self):
        # un job llamado que pide mas de lo que concede el llamador tumba el run entero (startup_failure)
        self.assertEqual(self.job["permissions"], {"contents": "read", "pull-requests": "write"})

    def test_ninguna_entrada_de_terceros_se_interpola_en_un_run(self):
        # titulo, rama y cuerpo del PR entran por entorno, nunca dentro del `run`
        for paso in self.job["steps"]:
            run = str(paso.get("run", ""))
            self.assertNotRegex(run, r"\$\{\{\s*github\.event\.pull_request\.(title|body|head\.ref)")
            self.assertNotIn("secrets.", run)

    def test_el_juez_lee_arquitectura_del_commit_base_no_del_head(self):
        texto = "\n".join(str(p.get("run", "")) for p in self.job["steps"])
        self.assertRegex(texto, r'git show "?\$PR_BASE_SHA:ARCHITECTURE\.md')

    def test_las_credenciales_solo_estan_en_el_paso_del_juez(self):
        con_secretos = [p.get("name") for p in self.job["steps"]
                        if re.search(r"secrets\.(JIRA|LITELLM)", str(p.get("env", "")))]
        self.assertEqual(con_secretos, ["Review"])

    def test_avisar_conoce_el_job_del_juez(self):
        avisar = JOBS["avisar"]
        self.assertIn("revisar_pr_juez", avisar["needs"])
        self.assertIn("needs.revisar_pr_juez.result", str(avisar["if"]))


def paso(job: str, nombre: str) -> dict:
    return next(p for p in JOBS[job]["steps"] if p.get("name") == nombre)


class TestCredencialesDelJuez(unittest.TestCase):
    """El juez usa credenciales PROPIAS (SC-2182) y no las de `propio` ni su modelo."""

    def test_el_paso_review_del_juez_usa_sus_secretos_y_su_modelo(self):
        env = paso("revisar_pr_juez", "Review")["env"]
        self.assertEqual({k: env[k] for k in ("REVIEW_LITELLM_KEY", "REVIEW_MODEL", "REVIEW_FALLBACK_MODEL",
                                              "REVIEW_JIRA_URL", "REVIEW_JIRA_EMAIL", "REVIEW_JIRA_TOKEN")}, {
            "REVIEW_LITELLM_KEY": "${{ secrets.LITELLM_JUEZ_KEY }}",
            "REVIEW_MODEL": "${{ inputs.juez_model }}",
            "REVIEW_FALLBACK_MODEL": "${{ inputs.fallback_model }}",
            "REVIEW_JIRA_URL": "${{ secrets.JIRA_JUEZ_URL }}",
            "REVIEW_JIRA_EMAIL": "${{ secrets.JIRA_JUEZ_EMAIL }}",
            "REVIEW_JIRA_TOKEN": "${{ secrets.JIRA_JUEZ_TOKEN }}"})

    def test_la_evaluacion_del_juez_usa_su_key_y_su_modelo(self):
        env = paso("evaluar_juez", "Evaluate the judge")["env"]
        self.assertEqual(env["REVIEW_LITELLM_KEY"], "${{ secrets.LITELLM_JUEZ_KEY }}")
        self.assertEqual(env["REVIEW_MODEL"], "${{ inputs.juez_model }}")
        self.assertEqual(env["REVIEW_FALLBACK_MODEL"], "${{ inputs.fallback_model }}")

    def test_el_juez_no_lee_lo_de_propio(self):
        for job in ("revisar_pr_juez", "evaluar_juez"):
            texto = str(JOBS[job])
            with self.subTest(job):
                self.assertNotRegex(texto, r"secrets\.(LITELLM_CI_KEY|JIRA_EMAIL|JIRA_API_TOKEN|PR_AGENT_LITELLM_KEY)")
                self.assertNotRegex(texto, r"inputs\.model\b")

    def test_propio_y_pr_agent_no_tocan_lo_del_juez(self):
        for job in ("revisar_pr", "revisar_pr_agent", "revisar_commit"):
            with self.subTest(job):
                self.assertNotRegex(str(JOBS[job]), r"JUEZ|juez_model")
        env = paso("revisar_pr", "Review")["env"]
        self.assertEqual(env["REVIEW_LITELLM_KEY"], "${{ secrets.LITELLM_CI_KEY }}")
        self.assertEqual(env["REVIEW_MODEL"], "${{ inputs.model }}")


if __name__ == "__main__":
    unittest.main()
