import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
# DGX-690 (G1 del architect): `spec.source.kustomize` (patches, commonLabels, images, namePrefix) lo aplica Argo al
# render igual que un `labels:` en lab/kustomization.yaml, que el contrato de k8s-ai ya prohibe (comentario 28759):
# la misma puerta trasera un nivel mas arriba y fuera de lo que ve ese contrato.
SOURCE_KEYS = {"repoURL", "targetRevision", "path"}


def source_violations(spec: dict) -> list[str]:
    out = [f"spec.source.{key}: no se admite, solo repoURL, targetRevision y path" for key in sorted(set(spec["source"]) - SOURCE_KEYS)]
    out += [f"spec.source.{key}: falta" for key in sorted(SOURCE_KEYS - set(spec["source"]))]
    if "sources" in spec:
        out.append("spec.sources: una sola fuente")
    return out


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

    def test_source_is_only_repo_revision_and_path(self) -> None:
        self.assertEqual(source_violations(self.spec), [])
        self.assertEqual(set(self.spec["source"]), SOURCE_KEYS)

    def test_negative_source_cannot_carry_a_transform(self) -> None:
        for extra in (
            {"kustomize": {"patches": [{"patch": "- op: add\n  path: /metadata/annotations/argocd.argoproj.io~1hook\n  value: PreSync"}]}},
            {"kustomize": {"commonLabels": {"gpu.dgx-infra/role": "resident"}}},
            {"kustomize": {"images": ["docker.io/vllm/vllm-openai:latest"]}},
            {"kustomize": {"namePrefix": "qwen38-flash-next-"}},
            {"directory": {"recurse": True}},
            {"helm": {"values": "a: b"}},
            {"plugin": {"name": "x"}},
        ):
            bad = source_violations({**self.spec, "source": {**self.spec["source"], **extra}})
            self.assertTrue(any(next(iter(extra)) in v for v in bad), extra)
        missing = {key: value for key, value in self.spec["source"].items() if key != "path"}
        self.assertTrue(any("path" in v and "falta" in v for v in source_violations({**self.spec, "source": missing})))
        self.assertTrue(any("sources" in v for v in source_violations({**self.spec, "sources": [self.spec["source"]]})))

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
