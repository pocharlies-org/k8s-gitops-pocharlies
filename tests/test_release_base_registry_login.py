"""The release job must hold credentials for the FROM's hostname (INFRA-1301).

Measured 2026-11-14 on shopify-back-in-stock (Release run 43654227972): the
build died with `401 Unauthorized` on the HEAD
`https://harbor.e-dani.com/v2/homelab/base-node/manifests/sha256:61b7a3ce...`.
The reusable logged into the push registry only (harbor.lan.e-dani.com), while
the bases fijadas por digest live under the canonical name of
docs/images/bases.md (harbor.e-dani.com) and the arc-k8s runner rejects
anonymous pulls of homelab. The `base_registry` input adds the second login
with the same robot (it reads homelab/* on both hostnames — the CI of
back-in-stock logs into harbor.e-dani.com and is green); the push stays on
`registry`, the LAN host, because pushing through harbor.e-dani.com hits the
413 of Cloudflare on layers over 100 MB (measured, skirmshop-affiliate-api).
"""

from __future__ import annotations

from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / ".github/workflows/reusable-release.yml"
LOGIN_SHA = "docker/login-action@dbcb813823bdd20940b903addbd779551569679f"


def workflow() -> dict:
    loaded = yaml.safe_load(RELEASE.read_text())
    # PyYAML reads the `on:` key as the boolean True (YAML 1.1).
    return loaded.get("on", loaded[True])


def steps() -> list[dict]:
    return yaml.safe_load(RELEASE.read_text())["jobs"]["release"]["steps"]


class BaseRegistryLogin(unittest.TestCase):
    def test_input_exists_off_by_default(self):
        inputs = workflow()["workflow_call"]["inputs"]
        self.assertEqual(inputs["base_registry"]["default"], "")

    def test_second_login_is_conditional_pinned_and_reuses_the_robot(self):
        base_logins = [
            step
            for step in steps()
            if str(step.get("uses", "")).startswith(LOGIN_SHA)
            and step.get("with", {}).get("registry") == "${{ inputs.base_registry }}"
        ]
        self.assertEqual(len(base_logins), 1, "exactly one base-registry login step")
        step = base_logins[0]
        self.assertEqual(
            step["if"],
            "${{ inputs.base_registry != '' && inputs.base_registry != inputs.registry }}",
            "login only when the base hostname differs from the push registry",
        )
        self.assertEqual(step["with"]["username"], "${{ secrets.HARBOR_USER }}")
        self.assertEqual(step["with"]["password"], "${{ secrets.HARBOR_PASSWORD }}")

    def test_push_login_is_untouched(self):
        push_logins = [
            step
            for step in steps()
            if str(step.get("uses", "")).startswith(LOGIN_SHA)
            and step.get("with", {}).get("registry") == "${{ inputs.registry }}"
        ]
        self.assertEqual(len(push_logins), 1)
        self.assertNotIn("if", push_logins[0], "the push login stays unconditional")


if __name__ == "__main__":
    unittest.main()
