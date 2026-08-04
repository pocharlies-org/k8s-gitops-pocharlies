"""Execute the exact manifest linkage step against hostile fixture variants."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/reusable-manifest-pr-release.yml"
VERSION = "rho-test"
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def download(url: str, destination: Path, sha256: str) -> None:
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - fixed URLs
        destination.write_bytes(response.read())
    actual = hashlib.sha256(destination.read_bytes()).hexdigest()
    if actual != sha256:
        raise AssertionError(f"checksum mismatch for {destination.name}: {actual}")


def install_tools(root: Path) -> Path:
    bin_dir = root / "bin"
    bin_dir.mkdir()
    node_archive = root / "node.tar.gz"
    download(
        "https://nodejs.org/dist/v24.19.0/node-v24.19.0-linux-x64.tar.gz",
        node_archive,
        "f625d97cd707df4ff96254916fbc5ff014f09c09effe5a1e0ca8f6d41a8789d4",
    )
    with tarfile.open(node_archive) as archive:
        archive.extract("node-v24.19.0-linux-x64/bin/node", root, filter="data")
    (bin_dir / "node").symlink_to(root / "node-v24.19.0-linux-x64/bin/node")

    kustomize_archive = root / "kustomize.tar.gz"
    download(
        "https://github.com/kubernetes-sigs/kustomize/releases/download/"
        "kustomize%2Fv5.5.0/kustomize_v5.5.0_linux_amd64.tar.gz",
        kustomize_archive,
        "6703a3a70a0c47cf0b37694030b54f1175a9dfeb17b3818b623ed58b9dbc2a77",
    )
    with tarfile.open(kustomize_archive) as archive:
        archive.extract("kustomize", bin_dir, filter="data")
    (bin_dir / "kustomize").chmod(0o755)

    helm_archive = root / "helm.tar.gz"
    download(
        "https://get.helm.sh/helm-v3.16.4-linux-amd64.tar.gz",
        helm_archive,
        "fc307327959aa38ed8f9f7e66d45492bb022a66c3e5da6063958254b9767d179",
    )
    with tarfile.open(helm_archive) as archive:
        member = archive.getmember("linux-amd64/helm")
        member.name = "helm"
        archive.extract(member, bin_dir, filter="data")
    (bin_dir / "helm").chmod(0o755)
    return bin_dir


def linkage_step() -> str:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return next(
        step["run"]
        for step in workflow["jobs"]["publish"]["steps"]
        if step.get("name") == "Stamp and verify exact release image digests"
    )


def create_fixture(root: Path) -> str:
    overlay = root / "deploy/kustomize"
    overlay.mkdir(parents=True)
    (overlay / "deployment.yaml").write_text(
        """apiVersion: apps/v1
kind: Deployment
metadata: {name: app}
spec:
  selector: {matchLabels: {app: app}}
  template:
    metadata: {labels: {app: app}}
    spec:
      containers:
        - name: app
          image: harbor.e-dani.com/homelab/app:old@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
""",
        encoding="utf-8",
    )
    (overlay / "kustomization.yaml").write_text(
        """apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources: [deployment.yaml]
images:
  - name: harbor.e-dani.com/homelab/app
    newTag: old
    digest: sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
""",
        encoding="utf-8",
    )

    chart = root / "deploy/chart"
    (chart / "templates").mkdir(parents=True)
    (chart / "Chart.yaml").write_text(
        "apiVersion: v2\nname: worker\nversion: 0.1.0\n", encoding="utf-8"
    )
    (chart / "values.yaml").write_text(
        json.dumps(
            {
                "image": {
                    "repository": "harbor.e-dani.com/homelab/worker",
                    "tag": "old",
                    "digest": DIGEST_B,
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (chart / "templates/deployment.yaml").write_text(
        """apiVersion: apps/v1
kind: Deployment
metadata: {name: worker}
spec:
  selector: {matchLabels: {app: worker}}
  template:
    metadata: {labels: {app: worker}}
    spec:
      containers:
        - name: worker
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}@{{ .Values.image.digest }}"
""",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "rho@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "RHO Test"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def promotions(source_sha: str) -> list[dict[str, str]]:
    def item(name: str, digest: str) -> dict[str, str]:
        repository = f"harbor.lan.e-dani.com/homelab/{name}"
        return {
            "name": name,
            "repository": repository,
            "versionRef": f"{repository}:{VERSION}",
            "shaRef": f"{repository}:sha-{source_sha[:12]}",
            "digest": digest,
            "ref": f"{repository}@{digest}",
        }

    return [item("app", DIGEST_A), item("worker", DIGEST_B)]


def targets() -> list[dict[str, object]]:
    return [
        {
            "name": "app",
            "kind": "kustomize",
            "path": "deploy/kustomize",
            "matchName": "harbor.e-dani.com/homelab/app",
            "deployRepository": "harbor.e-dani.com/homelab/app",
        },
        {
            "name": "worker",
            "kind": "helm-json",
            "path": "deploy/chart/values.yaml",
            "chartPath": "deploy/chart",
            "deployRepository": "harbor.e-dani.com/homelab/worker",
            "repositoryPath": ["image", "repository"],
            "tagPath": ["image", "tag"],
            "digestPath": ["image", "digest"],
        },
    ]


@unittest.skipUnless(platform.system() == "Linux" and platform.machine() in {"x86_64", "amd64"}, "verified linkage runtime fixture is Linux amd64 only")
class ReleaseImageLinkageRuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tools_root = Path(tempfile.mkdtemp(prefix="rho-linkage-tools-"))
        cls.bin_dir = install_tools(cls.tools_root)
        cls.step = linkage_step()

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tools_root)

    def execute(
        self, mutate=None, fixture_mutate=None
    ) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
        fixture = Path(tempfile.mkdtemp(prefix="rho-linkage-fixture-"))
        self.addCleanup(shutil.rmtree, fixture)
        create_fixture(fixture)
        if fixture_mutate:
            fixture_mutate(fixture)
            subprocess.run(["git", "add", "."], cwd=fixture, check=True)
            subprocess.run(["git", "commit", "-qm", "hostile fixture"], cwd=fixture, check=True)
        source_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=fixture, text=True
        ).strip()
        promotion_doc = promotions(source_sha)
        target_doc = targets()
        if mutate:
            promotion_doc, target_doc = mutate(promotion_doc, target_doc)
        runner_temp = Path(tempfile.mkdtemp(prefix="rho-linkage-runner-"))
        self.addCleanup(shutil.rmtree, runner_temp)
        script = runner_temp / "step.sh"
        script.write_text(self.step, encoding="utf-8")
        environment = {
            **os.environ,
            "PATH": f"{self.bin_dir}:{os.environ['PATH']}",
            "SOURCE_PATH": "deploy",
            "IMAGE_PROMOTIONS": json.dumps(promotion_doc, separators=(",", ":")),
            "IMAGE_TARGETS": json.dumps(target_doc, separators=(",", ":")),
            "REGISTRY": "harbor.lan.e-dani.com",
            "REGISTRY_PROJECT": "homelab",
            "VERSION": VERSION,
            "GITHUB_SHA": source_sha,
            "RUNNER_TEMP": str(runner_temp),
            "GITHUB_ENV": str(runner_temp / "github-env"),
        }
        result = subprocess.run(
            ["bash", str(script)], cwd=fixture, env=environment, text=True, capture_output=True
        )
        return result, fixture, runner_temp

    def test_exact_kustomize_and_helm_pins_share_one_patched_tree(self) -> None:
        result, fixture, runner_temp = self.execute()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        evidence = json.loads((fixture / "deploy/.rho-release.json").read_text())
        self.assertEqual(evidence["contractVersion"], "rho-release-linkage.v1")
        self.assertEqual({item["digest"] for item in evidence["images"]}, {DIGEST_A, DIGEST_B})
        environment = (runner_temp / "github-env").read_text()
        self.assertIn("PATCHED_TREE_SHA=", environment)
        self.assertIn("IMAGE_DIGEST_SET_SHA=", environment)
        cached = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only"], cwd=fixture, text=True
        ).splitlines()
        self.assertTrue(cached)
        self.assertTrue(all(path.startswith("deploy/") for path in cached))
        self.assertIn(f"rho-test@{DIGEST_A}", (runner_temp / "rendered-app.yaml").read_text())
        self.assertIn(f"rho-test@{DIGEST_B}", (runner_temp / "rendered-worker.yaml").read_text())

    def test_missing_target_fails_closed(self) -> None:
        result, _, _ = self.execute(lambda p, t: (p, t[:-1]))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exactly match", result.stderr)

    def test_forged_digest_fails_closed(self) -> None:
        def mutate(p, t):
            p[0]["ref"] = p[0]["repository"] + "@" + DIGEST_B
            return p, t

        result, _, _ = self.execute(mutate)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not bound", result.stderr)

    def test_target_escape_fails_closed(self) -> None:
        def mutate(p, t):
            t[0]["path"] = "../outside"
            return p, t

        result, _, _ = self.execute(mutate)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("safe relative path", result.stderr)

    def test_prototype_path_fails_closed(self) -> None:
        def mutate(p, t):
            t[1]["repositoryPath"] = ["constructor", "prototype", "polluted"]
            return p, t

        result, _, _ = self.execute(mutate)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bounded path array", result.stderr)

    def test_tracked_symlink_target_fails_closed(self) -> None:
        def fixture_mutate(fixture: Path) -> None:
            values = fixture / "deploy/chart/values.yaml"
            descriptor, outside_name = tempfile.mkstemp(prefix="rho-linkage-outside-", suffix=".json")
            os.close(descriptor)
            outside = Path(outside_name)
            self.addCleanup(outside.unlink, missing_ok=True)
            outside.write_text(values.read_text(), encoding="utf-8")
            values.unlink()
            values.symlink_to(outside)

        result, _, _ = self.execute(fixture_mutate=fixture_mutate)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tracked symlinks", result.stderr)


if __name__ == "__main__":
    unittest.main()
