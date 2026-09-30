"""Tests de INFRA-331: .pr_agent.toml y el reparto de secretos por repo.

Run: python3 -m unittest tests/test_pr_agent_config.py
Sin red ni secretos reales: el reparto corre contra un `gh` falso en el PATH y un Vault falso
en localhost. PR_AGENT_UPSTREAM_CONFIG (opcional) apunta al configuration.toml de la versión
fijada; el CI lo descarga verificado por sha256 y entonces también se comprueban las claves.
"""

from __future__ import annotations

import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / "scripts/check-pr-agent-config.py"
DIST = ROOT / "scripts/review-distribute-secrets.sh"
CONFIG = ROOT / ".pr_agent.toml"
SECRETS = ["PR_AGENT_LITELLM_KEY", "JIRA_EMAIL", "JIRA_API_TOKEN"]
VALUES = {"PR_AGENT_LITELLM_KEY": "sk-fake-litellm-0001", "JIRA_EMAIL": "ro@example.test",
          "JIRA_API_TOKEN": "fake-jira-token-0002"}
VAULT_TOKEN = "s.fake-vault-token-0003"

FAKE_GH = textwrap.dedent(r'''
    #!/usr/bin/env python3
    """gh falso: estado en $FAKE_GH_DIR/<owner>__<repo>.json = {"names": [...], "values": {...}}."""
    import json, os, sys
    d = os.environ["FAKE_GH_DIR"]; a = sys.argv[1:]
    def path(r): return os.path.join(d, r.replace("/", "__") + ".json")
    def fail(code):
        sys.stderr.write(f"gh: error (HTTP {code})\n"); sys.exit(1)
    deny = os.environ.get("FAKE_GH_DENY", "")
    if a[0] == "api":
        rest = [x for x in a[1:] if x != "--paginate"]
        route = rest[0]; parts = route.split("/")
        repo = "/".join(parts[1:3])
        if deny: fail(deny)
        if not os.path.exists(path(repo)): fail(404)
        st = json.load(open(path(repo)))
        if route.endswith("/actions/secrets"):
            print("\n".join(st["names"])); sys.exit(0)
        print("true" if st.get("admin", True) else "false"); sys.exit(0)
    if a[0] == "secret" and a[1] == "set":
        name = a[2]; repo = a[a.index("--repo") + 1]
        if deny: fail(deny)
        st = json.load(open(path(repo)))
        st.setdefault("values", {})[name] = sys.stdin.read()
        if name not in st["names"]: st["names"].append(name)
        json.dump(st, open(path(repo), "w")); sys.exit(0)
    sys.exit(3)
''').lstrip()

# curl espía: deja en $FAKE_CURL_LOG su argv y el modo de cada fichero -H @..., y ejecuta el real.
FAKE_CURL = textwrap.dedent(r'''
    #!/usr/bin/env python3
    import json, os, stat, sys
    a = sys.argv[1:]
    files = {x[1:]: oct(stat.S_IMODE(os.stat(x[1:]).st_mode)) for x in a if x.startswith("@")}
    with open(os.environ["FAKE_CURL_LOG"], "a") as f:
        f.write(json.dumps({"argv": a, "header_files": files}) + "\n")
    os.execv(os.environ["REAL_CURL"], ["curl", *a])
''').lstrip()


def load_check():
    import importlib.util
    spec = importlib.util.spec_from_file_location("check_pr_agent_config", CHECK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ConfigTest(unittest.TestCase):
    def run_check(self, text: str | None = None, upstream: bool = False):
        args = [sys.executable, str(CHECK)]
        with tempfile.TemporaryDirectory() as t:
            cfg = CONFIG
            if text is not None:
                cfg = Path(t) / "c.toml"
                cfg.write_text(text, encoding="utf-8")
            args += ["--config", str(cfg)]
            up = os.environ.get("PR_AGENT_UPSTREAM_CONFIG")
            if upstream:
                if not up:
                    self.skipTest("PR_AGENT_UPSTREAM_CONFIG no definido (lo pone el CI)")
                args += ["--upstream", up]
            return subprocess.run(args, capture_output=True, text=True)

    def mutate(self, section: str, key: str, value: str) -> str:
        lines, out, cur, done = CONFIG.read_text(encoding="utf-8").splitlines(), [], None, False
        for line in lines:
            if line.startswith("["):
                if cur == section and not done:
                    out.append(f"{key} = {value}"); done = True
                cur = line.strip("[] ").split("]")[0]
            if cur == section and line.split("=")[0].strip() == key:
                line, done = f"{key} = {value}", True
            out.append(line)
        if not done:
            out += [f"{key} = {value}"] if cur == section else [f"[{section}]", f"{key} = {value}"]
        return "\n".join(out) + "\n"

    def test_repo_config_valid(self):
        r = self.run_check()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_repo_config_keys_exist_upstream(self):
        r = self.run_check(upstream=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_decisions_in_file(self):
        data = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertIs(data["config"]["restricted_mode"], True)
        self.assertIs(data["github_action_config"]["auto_describe"], False)
        self.assertIs(data["github_action_config"]["auto_review"], True)
        self.assertIs(data["github_action_config"]["auto_improve"], True)
        self.assertIs(data["pr_reviewer"]["enable_review_labels_security"], False)
        self.assertEqual(data["config"]["model"], "openai/alibaba-q38-flash")
        self.assertEqual(sorted(data["jira"]["project_keys"]), ["DGX", "INFRA", "OWU", "SC", "SKIRM"])

    def test_broken_toml_fails(self):
        r = self.run_check("[config\nmodel = 'x'\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("TOML inválido", r.stdout)

    def test_decision_drift_fails(self):
        for section, key, value in [("github_action_config", "auto_describe", "true"),
                                    ("github_action_config", "auto_improve", "false"),
                                    ("github_action_config", "auto_review", "false"),
                                    ("pr_reviewer", "enable_review_labels_security", "true"),
                                    ("config", "restricted_mode", "false"),
                                    ("config", "model", '"openai/tooling"'),
                                    ("config", "fallback_models", '["gpt-5.6-terra"]'),
                                    ("jira", "project_keys", '["SC", "INFRA"]'),
                                    ("config", "ai_timeout", "0")]:
            with self.subTest(key=key):
                r = self.run_check(self.mutate(section, key, value))
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn(f"{section}.{key}", r.stdout)

    def test_missing_auto_flags_fail(self):
        # Sin declarar, PR-Agent las enciende todas (None = sí): tienen que ir explícitas.
        for line in ["auto_describe = false", "auto_improve = true", "auto_review = true"]:
            with self.subTest(line=line):
                text = CONFIG.read_text(encoding="utf-8").replace(line + "\n", "")
                r = self.run_check(text)
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn(line.split(" ")[0], r.stdout)

    def test_credentials_in_file_fail(self):
        for section, key in [("openai", "key"), ("jira", "jira_api_token"),
                             ("jira", "jira_api_email"), ("openai", "api_base")]:
            with self.subTest(key=key):
                r = self.run_check(self.mutate(section, key, '"x"'))
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn("va por entorno", r.stdout)

    def test_unknown_key_detected_with_upstream(self):
        with tempfile.TemporaryDirectory() as t:
            up = Path(t) / "configuration.toml"
            up.write_text("[config]\nmodel='a'\n# restricted_mode = false\n[jira]\n# jira_site = 'x'\n",
                          encoding="utf-8")
            mod = load_check()
            errors = mod.check({"config": {"model": "a", "restricted_mode": True, "response_langauge": "es"},
                                "jira": {"jira_site": "e"}, "nope": {"a": 1}}, mod.upstream_keys(up))
            text = "\n".join(errors)
            self.assertIn("config.response_langauge: clave desconocida", text)
            self.assertIn("[nope]: sección desconocida", text)
            self.assertNotIn("config.restricted_mode: clave desconocida", text)
            self.assertNotIn("jira.jira_site: clave desconocida", text)

    def test_missing_file_is_usage_error(self):
        r = subprocess.run([sys.executable, str(CHECK), "--config", "/nonexistent.toml"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


class _Vault(http.server.BaseHTTPRequestHandler):
    status = 200
    data: dict = {}
    seen_token = None

    def do_GET(self):  # noqa: N802
        _Vault.seen_token = self.headers.get("X-Vault-Token")
        ok = _Vault.seen_token == VAULT_TOKEN
        body = json.dumps({"data": {"data": self.data}} if ok else {"errors": ["permission denied"]}).encode()
        self.send_response(self.status if ok else 403)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class DistributeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.state, bindir = t / "state", t / "bin"
        self.state.mkdir(); bindir.mkdir()
        gh = bindir / "gh"
        gh.write_text(FAKE_GH, encoding="utf-8"); gh.chmod(0o755)
        curl = bindir / "curl"
        curl.write_text(FAKE_CURL, encoding="utf-8"); curl.chmod(0o755)
        self.curl_log = t / "curl.log"
        for repo, names in {"o/a": [], "o/b": ["JIRA_EMAIL"]}.items():
            (self.state / (repo.replace("/", "__") + ".json")).write_text(json.dumps({"names": names}))
        env = {k: v for k, v in os.environ.items() if k not in SECRETS + ["VAULT_ADDR", "VAULT_TOKEN"]}
        self.env = {**env, "PATH": f"{bindir}:{os.environ['PATH']}", "FAKE_GH_DIR": str(self.state),
                    "FAKE_CURL_LOG": str(self.curl_log), "REAL_CURL": shutil.which("curl") or "/usr/bin/curl"}

    def tearDown(self):
        self.tmp.cleanup()

    def run_dist(self, *args, env=None):
        return subprocess.run(["bash", str(DIST), *args], capture_output=True, text=True,
                              env={**self.env, **(env or {})})

    def repo(self, r):
        return json.loads((self.state / (r.replace("/", "__") + ".json")).read_text())

    def test_dry_run_lists_three_per_repo_without_values(self):
        r = self.run_dist("--dry-run", "--repos", "o/a,o/b", env=VALUES)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = [ln for ln in r.stdout.splitlines() if ln.startswith("repo=")]
        self.assertEqual(len(lines), 6)
        self.assertIn("repo=o/b secreto=JIRA_EMAIL estado=presente accion=ya-presente", r.stdout)
        self.assertIn("RESUMEN modo=dry-run repos=2 crear=5 rotar=0 ya-presente=1", r.stdout)
        for v in VALUES.values():
            self.assertNotIn(v, r.stdout + r.stderr)
        self.assertEqual(self.repo("o/a")["names"], [])

    def test_real_run_then_idempotent(self):
        r = self.run_dist("--repos", "o/a,o/b", env=VALUES)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for v in VALUES.values():
            self.assertNotIn(v, r.stdout + r.stderr)
        self.assertEqual(sorted(self.repo("o/a")["names"]), sorted(SECRETS))
        self.assertEqual(self.repo("o/a")["values"]["JIRA_API_TOKEN"], VALUES["JIRA_API_TOKEN"])
        self.assertNotIn("JIRA_EMAIL", self.repo("o/b").get("values", {}))  # presente: no se toca
        again = self.run_dist("--dry-run", "--repos", "o/a,o/b")
        self.assertEqual(again.returncode, 0)
        self.assertIn("crear=0 rotar=0 ya-presente=6", again.stdout)

    def test_rotate_overwrites(self):
        r = self.run_dist("--rotate", "--repos", "o/b", env=VALUES)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.repo("o/b")["values"]["JIRA_EMAIL"], VALUES["JIRA_EMAIL"])

    def test_missing_value_writes_nothing(self):
        env = {k: v for k, v in VALUES.items() if k != "JIRA_API_TOKEN"}
        r = self.run_dist("--repos", "o/a,o/b", env=env)
        self.assertEqual(r.returncode, 2)
        self.assertIn("resultado=bloqueado", r.stdout)
        self.assertEqual(self.repo("o/a")["names"], [])

    def test_from_vault(self):
        _Vault.status, _Vault.data = 200, dict(VALUES)
        srv = http.server.HTTPServer(("127.0.0.1", 0), _Vault)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            env = {"VAULT_ADDR": f"http://127.0.0.1:{srv.server_port}", "VAULT_TOKEN": VAULT_TOKEN}
            r = self.run_dist("--repos", "o/a", "--from-vault", "pr-review-ci", env=env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("fuente=vault", r.stdout)
            self.assertEqual(self.repo("o/a")["values"]["PR_AGENT_LITELLM_KEY"], VALUES["PR_AGENT_LITELLM_KEY"])
            # El token llega a Vault por cabecera, pero nunca está en el argv de curl ni en la
            # salida; el fichero de la cabecera es 0600 y no sobrevive a la ejecución.
            self.assertEqual(_Vault.seen_token, VAULT_TOKEN)
            calls = [json.loads(x) for x in self.curl_log.read_text().splitlines()]
            self.assertEqual(len(calls), 1)
            self.assertNotIn(VAULT_TOKEN, " ".join(calls[0]["argv"]))
            self.assertNotIn(VAULT_TOKEN, r.stdout + r.stderr)
            self.assertEqual(list(calls[0]["header_files"].values()), ["0o600"])
            for hdr in calls[0]["header_files"]:
                self.assertFalse(Path(hdr).exists())
            _Vault.status = 403
            r = self.run_dist("--dry-run", "--repos", "o/a", "--from-vault", "pr-review-ci", env=env)
            self.assertEqual(r.returncode, 4)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_vault_token_with_newline_rejected(self):
        # Un salto de línea en el token metería otra cabecera en el fichero -H @...
        env = {"VAULT_ADDR": "http://127.0.0.1:9", "VAULT_TOKEN": VAULT_TOKEN + "\nX-Other: 1"}
        r = self.run_dist("--dry-run", "--repos", "o/a", "--from-vault", "pr-review-ci", env=env)
        self.assertEqual(r.returncode, 2)
        self.assertFalse(self.curl_log.exists())
        self.assertNotIn(VAULT_TOKEN, r.stdout + r.stderr)

    def test_auth_error_exit_4(self):
        r = self.run_dist("--dry-run", "--repos", "o/a", env={"FAKE_GH_DENY": "403"})
        self.assertEqual(r.returncode, 4)

    def test_unknown_repo_and_usage(self):
        self.assertEqual(self.run_dist("--dry-run", "--repos", "o/zz").returncode, 2)
        self.assertEqual(self.run_dist("--dry-run").returncode, 2)
        self.assertEqual(self.run_dist("--dry-run", "--repos", "o/a;rm").returncode, 2)

    def test_brain_key_not_distributed(self):
        self.assertNotIn("BRAIN_CI_KEY", DIST.read_text(encoding="utf-8").split("set -Eeuo")[1])


if __name__ == "__main__":
    unittest.main()
