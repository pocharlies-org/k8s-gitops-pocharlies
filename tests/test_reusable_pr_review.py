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
MOTORES = ("revisar_pr_agent", "revisar_pr_juez", "evaluar_juez", "motor_invalido")


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
        for j in ("revisar_pr_agent", "revisar_pr_juez"):
            self.assertIn(j, JOBS)

    def test_un_solo_motor_en_un_pull_request(self):
        for engine, esperado in (("pr-agent", "revisar_pr_agent"),
                                 ("juez", "revisar_pr_juez")):
            with self.subTest(engine):
                self.assertEqual(en_marcha("pull_request", engine), [esperado])

    def test_un_solo_motor_en_workflow_dispatch(self):
        self.assertEqual(en_marcha("workflow_dispatch", "juez"), ["evaluar_juez"])
        self.assertEqual(en_marcha("workflow_dispatch", "pr-agent"), [])

    def test_un_solo_motor_desconocido_es_rojo_y_no_un_silencio_verde(self):
        # cada motor corre solo con su valor exacto: sin este job un typo saldria verde (D6).
        for evento in ("pull_request", "workflow_dispatch"):
            self.assertEqual(en_marcha(evento, "otro"), ["motor_invalido"])
        pasos = JOBS["motor_invalido"]["steps"]
        self.assertTrue(any("exit 2" in str(p.get("run", "")) for p in pasos))

    def test_el_job_del_juez_solo_corre_en_pull_request(self):
        for engine in ("pr-agent", "juez", "otro"):
            self.assertFalse(corre("revisar_pr_juez", "workflow_dispatch", engine))

    def test_el_nombre_del_check_del_juez(self):
        self.assertEqual(JOBS["revisar_pr_juez"]["name"], "Review del PR (juez)")


class TestSuperficieEstable(unittest.TestCase):
    """El nombre del check `<job> / <job>` y los inputs actuales no cambian; solo se suma."""

    def test_nombres_de_los_checks_de_siempre(self):
        self.assertEqual(JOBS["revisar_pr_agent"]["name"], "Review del PR (PR-Agent)")

    def test_inputs_actuales_intactos_y_fallback_model_aditivo(self):
        entradas = CUERPO[True]["workflow_call"]["inputs"]
        for nombre in ("engine", "runner", "model", "litellm_url", "max_diff_bytes", "telegram_topic",
                       "telegram_thread_id", "notificar"):
            self.assertIn(nombre, entradas)
        self.assertEqual(entradas["fallback_model"]["default"], "alibaba-q38-flash")
        self.assertEqual(entradas["fallback_model"]["type"], "string")
        # `model` se conserva como superficie de los llamadores (F4a: ya no lo lee ningun
        # motor); el juez tiene el suyo, aditivo (SC-2182)
        self.assertEqual(entradas["model"]["default"], "alibaba-q38-flash")
        self.assertEqual(entradas["juez_model"]["default"], "tooling")
        self.assertEqual(entradas["juez_model"]["type"], "string")

    def test_default_juez(self):
        # etapa (c) de SC-2182: el juez es el motor por defecto; `pr-agent` sigue seleccionable
        entrada = CUERPO[True]["workflow_call"]["inputs"]["engine"]
        self.assertEqual(entrada["default"], "juez")
        self.assertEqual(entrada["type"], "string")

    def test_default_juez_un_llamador_sin_engine_corre_solo_el_juez(self):
        # `inputs.engine` toma el default cuando el llamador no lo fija: es lo que ven los repos de la plantilla
        engine = CUERPO[True]["workflow_call"]["inputs"]["engine"]["default"]
        self.assertEqual(en_marcha("pull_request", engine), ["revisar_pr_juez"])
        self.assertEqual(en_marcha("workflow_dispatch", engine), ["evaluar_juez"])

    def test_los_secretos_propios_del_juez_son_opcionales_y_los_de_siempre_siguen(self):
        secretos = CUERPO[True]["workflow_call"]["secrets"]
        for nombre in ("LITELLM_JUEZ_KEY", "JIRA_JUEZ_EMAIL", "JIRA_JUEZ_TOKEN", "JIRA_JUEZ_URL"):
            self.assertIn(nombre, secretos)
            self.assertFalse(secretos[nombre]["required"], nombre)
        for nombre in ("LITELLM_CI_KEY", "JIRA_EMAIL", "JIRA_API_TOKEN"):   # pr-agent (LITELLM_CI_KEY: superficie conservada, F4a)
            self.assertIn(nombre, secretos)

    def test_los_outputs_del_reusable_incluyen_el_juez(self):
        salidas = CUERPO[True]["workflow_call"]["outputs"]
        for nombre in ("veredicto", "n_hallazgos"):
            self.assertIn("revisar_pr_juez", salidas[nombre]["value"])


class TestTokenDeHindsight(unittest.TestCase):
    """SC-4304 S5: el token `pr-review` (solo escritura, banco `ops`) llega a UN paso y nunca a un `run`."""

    def pasos_con(self, clave):
        return [p for p in JOBS["revisar_pr_agent"]["steps"] if clave in (p.get("env") or {})]

    def test_solo_el_paso_de_distribucion_lo_recibe_y_con_guarda_de_fork(self):
        pasos = self.pasos_con("HINDSIGHT_WRITER_TOKEN")
        self.assertEqual([p["id"] for p in pasos], ["distribucion"])
        self.assertIn("steps.guarda.outputs.fork != 'true'", pasos[0]["if"])
        self.assertEqual(pasos[0]["env"]["HINDSIGHT_WRITER_TOKEN"], "${{ secrets.HINDSIGHT_WRITER_TOKEN }}")

    def test_ningun_paso_recibe_la_clave_del_brain(self):
        # la lectura (S5) y la escritura (SC-4304 fase 2) del Brain se retiraron: BRAIN_CI_KEY no llega a ningún paso
        self.assertEqual(self.pasos_con("BRAIN_CI_KEY"), [])
        self.assertNotIn("BRAIN_CI_KEY", CUERPO[True]["workflow_call"]["secrets"])

    def test_el_secreto_es_opcional_y_el_workflow_no_usa_pull_request_target(self):
        self.assertFalse(CUERPO[True]["workflow_call"]["secrets"]["HINDSIGHT_WRITER_TOKEN"]["required"])
        self.assertNotIn("pull_request_target", WORKFLOW.read_text(encoding="utf-8").replace("NUNCA `pull_request_target`", ""))

    def test_ningun_run_interpola_el_token(self):
        for job in JOBS.values():
            for paso in job.get("steps", []):
                self.assertNotIn("HINDSIGHT_WRITER_TOKEN", str(paso.get("run", "")).replace("$HINDSIGHT_WRITER_TOKEN", ""))


class TestJuezAislado(unittest.TestCase):
    def setUp(self):
        self.job = JOBS["revisar_pr_juez"]

    def test_permisos_minimos(self):
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


def _filas(nombre: str) -> list[list[str]]:
    """Filas de una lista de `.github/`: columnas por TAB; `#` y lineas en blanco son comentarios."""
    out = []
    for linea in (ROOT / ".github" / nombre).read_text(encoding="utf-8").splitlines():
        if linea.strip() and not linea.lstrip().startswith("#"):
            out.append(linea.split("\t"))
    return out


class TestCoberturaDelJuez(unittest.TestCase):
    """SC-2182 C15 (N1): ningun repo ve un SIN_VEREDICTO rojo por el cambio del `engine` por defecto.

    Sin red: las listas son lo medido (`pr-review-llamadores.txt`: todos los repos que llaman al
    reusable; `pr-review-juez-repos.txt`: donde la compania abre PRs) y la comprobacion viva es
    `scripts/review-distribute-secrets.sh --dry-run` (docs/ci-pr-review.md). Este test cruza las listas
    con el default del reusable: el default es `juez`, asi que ningun `pendiente` admitido. Un repo solo
    queda cubierto por secretos, por `engine` fijado, archivado o `excluido` con su motivo.
    """

    ESTADOS = {"activo", "archivado"}
    # F4a (INFRA-334): dos motores; el vocabulario `propio` ya no existe.
    COBERTURAS = {"secretos", "pr-agent", "archivado", "excluido", "pendiente"}
    ENGINES = {"default", "pr-agent", "juez"}

    def setUp(self):
        self.llam = {f[0]: f for f in _filas("pr-review-llamadores.txt")}
        self.juez = _filas("pr-review-juez-repos.txt")

    def test_cobertura_formato_y_sin_repetidos(self):
        filas = _filas("pr-review-llamadores.txt")
        self.assertEqual(len(filas), len(self.llam), "un repo repetido en pr-review-llamadores.txt")
        self.assertEqual([f[0] for f in filas], sorted(self.llam))
        for repo, estado, engine, ref, cobertura, *resto in filas:
            motivo = resto[0].strip() if resto else ""
            self.assertRegex(repo, r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
            # `excluido` (el repo no recibe el juez ni fija un motor) exige decir por que; el resto no lleva motivo
            self.assertEqual(bool(motivo), cobertura == "excluido", f"{repo}: el motivo va solo con `excluido` y es obligatorio")
            self.assertIn(estado, self.ESTADOS, repo)
            self.assertIn(engine, self.ENGINES, repo)
            self.assertRegex(ref, r"^(main|sha:[0-9a-f]{12})$", repo)
            self.assertIn(cobertura, self.COBERTURAS, repo)

    def test_cobertura_engine_fijado_es_coherente(self):
        # `pr-agent` como cobertura es el engine fijado en el repo, y al reves
        for repo, estado, engine, _, cobertura, *_ in self.llam.values():
            if estado == "archivado":
                self.assertEqual(cobertura, "archivado", repo)
            elif cobertura == "pr-agent":
                self.assertEqual(engine, "pr-agent", repo)
            elif engine == "pr-agent":
                self.assertEqual(cobertura, "pr-agent", repo)
            else:
                self.assertIn(cobertura, ("secretos", "excluido", "pendiente"), repo)

    def test_cobertura_pr_agent_es_la_lista_de_pr_agent(self):
        pilotos = {f[0] for f in _filas("pr-agent-repos.txt")}
        con_pr_agent = {r for r, f in self.llam.items() if f[2] == "pr-agent"}
        self.assertEqual(con_pr_agent, pilotos)

    def test_cobertura_los_repos_del_juez_llaman_y_nunca_se_excluyen(self):
        repos = [f[0] for f in self.juez]
        self.assertEqual(repos, sorted(repos))
        self.assertEqual(len(repos), len(set(repos)))
        for repo, llama, proyectos, *_ in self.juez:
            self.assertIn(llama, ("llama", "no-llama"), repo)
            self.assertRegex(proyectos, r"^(SC|DGX|INFRA|SKIRM|OWU|LE|ACC)(,(SC|DGX|INFRA|SKIRM|OWU|LE|ACC))*$", repo)
            self.assertEqual(llama == "llama", repo in self.llam, f"{repo}: la lista del juez y la de llamadores no coinciden")
            if repo in self.llam:
                self.assertNotIn(self.llam[repo][4], ("excluido",),
                                 f"{repo} es del juez: no puede quedar excluido")

    def test_cobertura_cada_excepcion_del_juez_lleva_su_nota(self):
        for repo, llama, _, *resto in self.juez:
            nota = resto[0] if resto else ""
            f = self.llam.get(repo)
            excepcion = f is None or f[1] == "activo" and (f[2] != "default" or f[3] != "main")
            if excepcion and not (f is None and nota.startswith("archivado")):
                self.assertTrue(nota.strip(), f"{repo}: llama a mano, fija engine o apunta por SHA y no lo dice")

    def test_cobertura_con_el_default_en_juez_no_queda_ningun_pendiente(self):
        default = CUERPO[True]["workflow_call"]["inputs"]["engine"]["default"]
        self.assertEqual(default, "juez")
        pendientes = sorted(r for r, f in self.llam.items() if f[4] == "pendiente")
        self.assertEqual(pendientes, [], "el default es juez y hay repos sin secretos ni engine fijado")

def paso(job: str, nombre: str) -> dict:
    return next(p for p in JOBS[job]["steps"] if p.get("name") == nombre)


class TestCredencialesDelJuez(unittest.TestCase):
    """El juez usa credenciales propias (SC-2182) y no las de pr-agent ni su modelo."""

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

    def test_el_juez_no_lee_lo_de_pr_agent(self):
        for job in ("revisar_pr_juez", "evaluar_juez"):
            texto = str(JOBS[job])
            with self.subTest(job):
                self.assertNotRegex(texto, r"secrets\.(LITELLM_CI_KEY|JIRA_EMAIL|JIRA_API_TOKEN|PR_AGENT_LITELLM_KEY)")
                self.assertNotRegex(texto, r"inputs\.model\b")

    def test_pr_agent_no_toca_lo_del_juez(self):
        self.assertNotRegex(str(JOBS["revisar_pr_agent"]), r"JUEZ|juez_model")


class TestJuezV3(unittest.TestCase):
    """SC-2285 C14: el job del juez da 20 min, la plantilla escucha `ready_for_review` y lo demas no cambia."""

    def test_el_job_del_juez_tiene_20_minutos_y_el_mismo_nombre_y_permisos(self):
        job = JOBS["revisar_pr_juez"]
        self.assertEqual(job["timeout-minutes"], 20)
        self.assertEqual(job["name"], "Review del PR (juez)")
        self.assertEqual(job["permissions"], {"contents": "read", "pull-requests": "write"})

    def test_el_juez_recibe_el_borrador_del_evento_como_respaldo_de_la_api(self):
        env = paso("revisar_pr_juez", "Review")["env"]
        self.assertEqual(env["REVIEW_PR_DRAFT"], "${{ github.event.pull_request.draft }}")
        self.assertEqual(env["REVIEW_GITHUB_TOKEN"], "${{ github.token }}")   # con el mismo token lee la PR y los ficheros

    def test_la_evaluacion_usa_pasadas_y_max_falsos(self):
        run = paso("evaluar_juez", "Evaluate the judge")["run"]
        self.assertIn("--pasadas 3 --max-falsos 0.10", run)
        self.assertNotIn("--umbral", run)

    def test_la_plantilla_escucha_ready_for_review(self):
        plantilla = yaml.safe_load((ROOT / "templates/ci/pr-review.yml").read_text(encoding="utf-8"))
        self.assertEqual(plantilla[True]["pull_request"]["types"],
                         ["opened", "synchronize", "reopened", "ready_for_review"])
        self.assertEqual(plantilla["jobs"]["review"]["uses"],
                         "pocharlies-org/k8s-gitops-pocharlies/.github/workflows/reusable-pr-review.yml@main")

    def test_los_inputs_y_el_resto_de_motores_no_cambian(self):
        entradas = CUERPO[True]["workflow_call"]["inputs"]
        self.assertEqual(entradas["engine"]["default"], "juez")
        self.assertEqual(entradas["juez_model"]["default"], "tooling")
        self.assertEqual(en_marcha("pull_request", "juez"), ["revisar_pr_juez"])


class TestInvariantesINFRA298(unittest.TestCase):
    """INFRA-298 (validación final de la épica; qa midió a mano en `70-qa.md` de INFRA-334): las
    invariantes del sistema de review quedan fijadas aquí, sin red, sobre los ficheros que mide la
    señal nocturna. Reutilizan `en_marcha`/`JOBS`/`WORKFLOW`/`_filas` de este módulo.

    No se repite lo que ya comprueban las clases de arriba:
      - pr-agent-repos == {llamadores con engine pr-agent} (=> pr-agent ⊆ llamadores y "un repo no
        corre los dos motores" por el valor único de `engine`):
        TestCoberturaDelJuez.test_cobertura_pr_agent_es_la_lista_de_pr_agent
      - forma del job del juez (timeout/nombre/permisos/env): TestJuezAislado y TestJuezV3
      - el formato del marcador v3 que emite review.py: tests/test_llm_review_juez.py
    Se fija lo que eso no cubre: que el único repo en las dos listas es un piloto que declara
    pr-agent (1), que el motor `propio` retirado en F4a no vuelve (2, = grep `engine.*propio` de qa),
    y que el contrato del marcador v3 y el job que lo emite siguen ahí (3, = grep CONTRACT de qa).
    """

    def setUp(self):
        self.llam = {f[0]: f for f in _filas("pr-review-llamadores.txt")}

    # (1) coherencia de listas: un repo no corre los dos motores.
    def test_un_repo_no_corre_los_dos_motores(self):
        # qa midió (criterio 2) que los pilotos k8s-litellm y skirmshop-labels están en las dos
        # listas: es correcto porque fijan `engine: pr-agent`, así que el juez queda SKIPPED. La
        # invariante NO es que las listas sean disjuntas (no lo son), sino que un repo que aparece
        # en la del juez y además es piloto lo declara: si alguien mete en pr-agent-repos un repo
        # que corre juez por defecto, aquí salta (eso sí sería correr los dos motores).
        pr_agent = {f[0] for f in _filas("pr-agent-repos.txt")}
        juez = {f[0] for f in _filas("pr-review-juez-repos.txt")}
        for repo in sorted(pr_agent & juez):
            fila = next(f for f in _filas("pr-review-juez-repos.txt") if f[0] == repo)
            nota = fila[3] if len(fila) > 3 else ""
            self.assertRegex(nota, r"engine:\s*pr-agent",
                             f"{repo}: en pr-agent-repos y en la lista del juez sin declarar que "
                             f"fija engine: pr-agent (se leería como doble motor)")
            # y su motor declarado en llamadores es pr-agent, no el default juez
            self.assertEqual(self.llam[repo][2], "pr-agent", repo)

    # (2) el motor `propio` retirado (F4a, INFRA-334) no puede volver.
    def test_el_motor_propio_no_es_un_motor(self):
        # `propio` cae al job que pinta rojo (motor_invalido): no tiene motor asignado, como
        # cualquier valor desconocido. El enum de hecho del reusable admite solo pr-agent y juez.
        for evento in ("pull_request", "workflow_dispatch"):
            with self.subTest(evento):
                self.assertEqual(en_marcha(evento, "propio"), ["motor_invalido"])

    def test_el_reusable_no_menciona_engine_propio(self):
        # el grep de qa (criterio 8.i): `engine.*propio` vacío en el reusable. La palabra `propio`
        # vive en prosa («TELEGRAM_BOT_TOKEN propio», «su propio»), pero nunca con `engine` delante
        # en la misma línea: ese patrón es el que midió qa y debe seguir sin casar.
        self.assertNotRegex(WORKFLOW.read_text(encoding="utf-8"), r"engine.*propio")

    # (3) el contrato del marcador v3 y el job que lo emite siguen presentes.
    def test_el_contrato_del_marcador_v3_sigue_en_review_py(self):
        # el grep de qa (criterio 8.iii): la línea de contrato del marcador que lee company-aprobar.
        review = (ROOT / ".github/actions/llm-review/review.py").read_text(encoding="utf-8")
        self.assertIn("CONTRACT: ci.llm-review-bot.marcador.v3", review)

    def test_el_job_del_juez_sigue_emitiendo_el_marcador(self):
        # "el juez sobrevive" (qa 8.iii): el job del juez sigue llamando al revisor en modo --juez,
        # que es lo que publica el marcador v3. Su forma (timeout/nombre/permisos) la fijan
        # TestJuezAislado y TestJuezV3; aquí solo el vínculo con el marcador.
        run = "\n".join(str(p.get("run", "")) for p in JOBS["revisar_pr_juez"]["steps"])
        self.assertIn("--juez", run)


if __name__ == "__main__":
    unittest.main()
