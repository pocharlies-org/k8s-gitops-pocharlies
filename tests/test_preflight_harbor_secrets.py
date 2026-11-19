"""INFRA-1459: el pre-flight de HARBOR_* falla nombrando los secrets que faltan.

Cubre los criterios de la historia: mensaje accionable (no startup_failure
opaco), comando de siembra presente, ningun valor de secreto impreso, y los
cuatro reusables cubiertos con el pre-flight antes de cualquier login/build.
"""
import os
import pathlib
import subprocess

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
ACTION = ROOT / ".github/actions/preflight-harbor-secrets/action.yml"
REUSABLES = [
    "reusable-release",
    "reusable-manifest-release",
    "reusable-manifest-pr-release",
    "reusable-deploy-stg",
]


def _script():
    action = yaml.safe_load(ACTION.read_text())
    step = action["runs"]["steps"][0]
    assert step["shell"] == "bash"
    return step["run"]


def _run(**secrets):
    env = dict(os.environ)
    env["REPO"] = "pocharlies-org/demo"
    env.update(secrets)
    return subprocess.run(
        ["bash", "-e", "-c", _script()],
        capture_output=True,
        text=True,
        env=env,
    )


def test_falla_nombrando_los_secrets_y_el_comando():
    r = _run(HARBOR_USER="", HARBOR_PASSWORD="")
    assert r.returncode == 1
    out = r.stdout + r.stderr
    assert "HARBOR_USER" in out and "HARBOR_PASSWORD" in out
    assert "company-repo-alta --sembrar pocharlies-org/demo" in out
    assert "gh secret set HARBOR_USER -R pocharlies-org/demo" in out
    assert "gh secret set HARBOR_PASSWORD -R pocharlies-org/demo" in out


def test_pasa_con_los_secrets_y_no_imprime_valores():
    r = _run(HARBOR_USER="robot$ci", HARBOR_PASSWORD="MARCA_SECRETA_NO_IMPRIMIBLE")
    assert r.returncode == 0
    assert "MARCA_SECRETA_NO_IMPRIMIBLE" not in r.stdout + r.stderr


def test_un_secrets_vacio_tambien_falla():
    r = _run(HARBOR_USER="robot$ci", HARBOR_PASSWORD="")
    assert r.returncode == 1
    assert "HARBOR_PASSWORD" in r.stdout + r.stderr


def _steps(name):
    wf = yaml.safe_load((ROOT / f".github/workflows/{name}.yml").read_text())
    return wf[True]["workflow_call"], wf["jobs"]


def test_cuatro_reusables_cubiertos_antes_del_login():
    for name in REUSABLES:
        call, jobs = _steps(name)
        for secret in ("HARBOR_USER", "HARBOR_PASSWORD"):
            assert call["secrets"][secret]["required"] is False, (name, secret)
        steps = next(iter(jobs.values()))["steps"]
        uses = [str(s.get("uses", "")) + " " + str(s.get("name", "")) for s in steps]
        preflight = [i for i, u in enumerate(uses) if "preflight-harbor-secrets" in u]
        assert preflight, name
        danger = [
            i
            for i, u in enumerate(uses)
            if "login-action" in u or "Login to Harbor" in u or "Build and push" in u
        ]
        assert danger, name
        assert preflight[0] < min(danger), (name, preflight[0], danger)
