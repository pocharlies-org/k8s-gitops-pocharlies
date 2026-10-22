from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class CorreoApplicationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.application = yaml.safe_load(
            (ROOT / "apps/correo.yaml").read_text(encoding="utf-8")
        )
        self.spec = self.application["spec"]

    def test_two_sources_chart_by_oci_and_values_repo(self) -> None:
        # DGX-880 P9 (A5): como apps/langfuse.yaml, con el chart por OCI. Nunca una fuente
        # única con `path: k8s`: el chart y los values de Skirmshop viven en repos distintos.
        self.assertEqual(self.application["metadata"]["name"], "correo")
        self.assertNotIn("source", self.spec)
        chart, values = self.spec["sources"]
        self.assertEqual(
            chart,
            {
                # Sin `oci://`: ArgoCD lo añade (como el chart de ARC en infra/arc.yaml).
                "repoURL": "harbor.lan.e-dani.com/homelab/charts",
                "chart": "correo",
                "targetRevision": "0.5.0",
                "helm": {
                    "releaseName": "correo",
                    "valueFiles": ["$values/k8s/values-skirmshop.yaml"],
                },
            },
        )
        self.assertEqual(
            values,
            {
                "repoURL": "https://github.com/pocharlies-org/k8s-correo-pocharlies",
                "targetRevision": "deploy/prod",
                "ref": "values",
                "path": "k8s/platform",
                # ExternalSecrets, HMAC generados y backup viven en subcarpetas (P8).
                "directory": {"recurse": True},
            },
        )
        # El fichero de values no puede caer bajo `path`: se aplicaría como manifiesto.
        value_file = chart["helm"]["valueFiles"][0].removeprefix("$values/")
        self.assertFalse(value_file.startswith(values["path"] + "/"))
        self.assertEqual(self.spec["destination"]["namespace"], "correo")

    def test_sync_is_manual_until_the_first_sync(self) -> None:
        # Sin `automated` hasta el primer sync (como apps/company-crm.yaml): el chart sale de
        # Harbor y necesita la credencial OCI de ArgoCD (DGX-916) antes de resolverse.
        policy = self.spec["syncPolicy"]
        self.assertNotIn("automated", policy)
        self.assertIn("CreateNamespace=true", policy["syncOptions"])
        self.assertIn("ServerSideApply=true", policy["syncOptions"])

    def test_namespace_is_created_restricted(self) -> None:
        # S19: el ns `correo` lo crea la Application con Pod Security `restricted` en los tres modos.
        labels = self.spec["syncPolicy"]["managedNamespaceMetadata"]["labels"]
        for mode in ("enforce", "audit", "warn"):
            self.assertEqual(labels[f"pod-security.kubernetes.io/{mode}"], "restricted")

    def test_root_kustomization_includes_application(self) -> None:
        root = yaml.safe_load((ROOT / "kustomization.yaml").read_text(encoding="utf-8"))
        self.assertIn("apps/correo.yaml", root["resources"])


if __name__ == "__main__":
    unittest.main()
