import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class AiLabApplicationTest(unittest.TestCase):
    """DGX-689: el laboratorio de dgx3 es una Application aparte de `ai`, sin hooks del arbitro."""

    def setUp(self) -> None:
        self.source_text = (ROOT / "apps/ai-lab.yaml").read_text(encoding="utf-8")
        self.application = yaml.safe_load(self.source_text)
        self.spec = self.application["spec"]

    def test_renders_only_lab_of_k8s_ai_pinned_to_a_commit(self) -> None:
        self.assertEqual(self.application["metadata"]["name"], "ai-lab")
        source = self.spec["source"]
        self.assertEqual(source["repoURL"], "https://github.com/pocharlies-org/k8s-ai-pocharlies")
        self.assertEqual(source["path"], "lab")
        # Un SHA, no una rama: cambiar el laboratorio tiene que ser un PR aqui.
        self.assertRegex(source["targetRevision"], r"^[0-9a-f]{40}$")

    def test_lives_outside_the_arbiter_namespace(self) -> None:
        self.assertEqual(self.spec["destination"]["namespace"], "ai-lab")

    def test_option_b_replicas_are_owned_by_git_only(self) -> None:
        self.assertNotIn("ignoreDifferences", self.spec)
        self.assertTrue(self.spec["syncPolicy"]["automated"]["selfHeal"])

    def test_no_arbiter_hooks_or_pause_flags(self) -> None:
        self.assertNotIn("argocd.argoproj.io/hook", self.source_text)
        self.assertNotIn("skip-reconcile", self.source_text)

    def test_root_kustomization_includes_application(self) -> None:
        root = yaml.safe_load((ROOT / "kustomization.yaml").read_text(encoding="utf-8"))
        self.assertIn("apps/ai-lab.yaml", root["resources"])


if __name__ == "__main__":
    unittest.main()
