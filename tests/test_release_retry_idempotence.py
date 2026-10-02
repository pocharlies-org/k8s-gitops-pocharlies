"""A release retry on a commit that already published must converge (INFRA-352).

Measured 2026-09-30 on k8s-socialmedia-pocharlies: the image build is not
reproducible and the ORAS manifest carries a creation timestamp, so a second
run on the same commit produced other digests and collided with the immutable
`sha-<commit>` tag the first run had left (runs 36699101771 -> 36701685011).
A run whose VERSION already belonged to another commit published
`sha-<commit>` before failing on VERSION, poisoning every later retry.

These tests run the code extracted verbatim from the reusable workflows:

* the image preflight decision (node) of reusable-release.yml;
* the whole "Publish Argo CD OCI manifest bundle" step of
  reusable-manifest-release.yml against a fake Harbor API and a fake ORAS;
* the legacy deploy-branch promotion step against a real bare Git remote.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import textwrap
import unittest
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / ".github/workflows/reusable-release.yml"
MANIFEST = ROOT / ".github/workflows/reusable-manifest-release.yml"
DECISION = re.compile(r"\n( *// RELEASE_PREFLIGHT_DECISION[^\n]*\n.*?)\n          NODE\n", re.S)
REVISION = "a" * 40
OTHER_REVISION = "b" * 40
DIGEST_A = "sha256:" + "1" * 64
DIGEST_B = "sha256:" + "2" * 64


def node_binary(tools: Path) -> str:
    found = shutil.which("node")
    if found:
        return found
    if not (platform.system() == "Linux" and platform.machine() in {"x86_64", "amd64"}):
        raise unittest.SkipTest("no node on PATH and the verified download is Linux amd64 only")
    archive = tools / "node.tar.gz"
    with urllib.request.urlopen(  # noqa: S310 - fixed URL, checksum verified below
        "https://nodejs.org/dist/v24.19.0/node-v24.19.0-linux-x64.tar.gz", timeout=60
    ) as response:
        archive.write_bytes(response.read())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != "f625d97cd707df4ff96254916fbc5ff014f09c09effe5a1e0ca8f6d41a8789d4":
        raise AssertionError(f"node checksum mismatch: {digest}")
    with tarfile.open(archive) as bundle:
        bundle.extract("node-v24.19.0-linux-x64/bin/node", tools, filter="data")
    return str(tools / "node-v24.19.0-linux-x64/bin/node")


def decision_source() -> str:
    match = DECISION.search(RELEASE.read_text(encoding="utf-8"))
    if match is None:  # pragma: no cover - the preflight lost its decision entirely
        raise AssertionError("could not find RELEASE_PREFLIGHT_DECISION in reusable-release.yml")
    return textwrap.dedent(match.group(1))


def step_script(workflow: Path, name: str) -> str:
    document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    return next(
        step["run"] for step in document["jobs"]["publish"]["steps"] if step.get("name") == name
    )


def image_artifact(digest: str, revision: str | None) -> dict:
    labels = {} if revision is None else {"org.opencontainers.image.revision": revision}
    return {"digest": digest, "extra_attrs": {"config": {"Labels": labels}}}


class ImagePreflightDecisionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tools = Path(tempfile.mkdtemp(prefix="rho-retry-tools-"))
        cls.node = node_binary(cls.tools)
        cls.source = decision_source()

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tools)

    def decide(self, sha: dict | None, version: dict | None, sha_status: str | None = None):
        with tempfile.TemporaryDirectory() as tmp:
            sha_file = Path(tmp) / "sha.json"
            version_file = Path(tmp) / "version.json"
            sha_file.write_text(json.dumps(sha or {"errors": []}))
            version_file.write_text(json.dumps(version or {"errors": []}))
            return subprocess.run(  # noqa: S603 - node, fixed args
                [self.node, "-e", self.source],
                env={
                    **os.environ,
                    "NAME": "app",
                    "SHA_TAG": "sha-aaaaaaaaaaaa",
                    "VERSION": "v1.2.3",
                    "EXPECTED_REVISION": REVISION,
                    "SHA_TAG_STATUS": sha_status or ("200" if sha else "404"),
                    "SHA_TAG_FILE": str(sha_file),
                    "VERSION_STATUS": "200" if version else "404",
                    "VERSION_FILE": str(version_file),
                },
                capture_output=True,
                text=True,
                check=False,
            )

    def test_new_commit_and_new_version_builds(self) -> None:
        result = self.decide(None, None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "build")

    def test_retry_after_sha_tag_was_published_reuses_that_digest(self) -> None:
        result = self.decide(image_artifact(DIGEST_A, REVISION), None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"reuse\t{DIGEST_A}")

    def test_retry_of_a_fully_published_release_reuses_that_digest(self) -> None:
        result = self.decide(image_artifact(DIGEST_A, REVISION), image_artifact(DIGEST_A, REVISION))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"reuse\t{DIGEST_A}")

    def test_version_owned_by_another_commit_fails_before_anything_is_built(self) -> None:
        # Run 36699101771: v1.3.71 already belonged to 74526df9.
        result = self.decide(None, image_artifact(DIGEST_B, OTHER_REVISION))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already published as", result.stderr)
        self.assertIn("unused image_tag", result.stderr)

    def test_version_on_another_digest_than_this_commit_fails(self) -> None:
        result = self.decide(image_artifact(DIGEST_A, REVISION), image_artifact(DIGEST_B, OTHER_REVISION))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("never moved", result.stderr)

    def test_sha_tag_bound_to_another_revision_fails(self) -> None:
        result = self.decide(image_artifact(DIGEST_A, OTHER_REVISION), None)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is bound to revision", result.stderr)

    def test_unlabelled_sha_tag_is_left_to_the_signature_binding(self) -> None:
        result = self.decide(image_artifact(DIGEST_A, None), None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"reuse\t{DIGEST_A}")

    def test_non_canonical_digest_fails_closed(self) -> None:
        result = self.decide({"digest": "sha256:short"}, None)
        self.assertNotEqual(result.returncode, 0)

    def test_unexpected_lookup_status_fails_closed(self) -> None:
        result = self.decide(image_artifact(DIGEST_A, REVISION), None, sha_status="500")
        self.assertNotEqual(result.returncode, 0)


FAKE_CURL = r'''#!/usr/bin/env python3
"""Fake Harbor v2.0 API: artifact lookup, nested tag list and atomic CreateTag."""
import json, os, sys, urllib.parse
state_path = os.environ["FAKE_HARBOR_STATE"]
state = json.load(open(state_path))
args = sys.argv[1:]
output = write_out = data = None
method = "GET"
url = None
i = 0
while i < len(args):
    arg = args[i]
    if arg in ("--output", "--write-out", "--request", "--data", "--header", "--netrc-file"):
        value = args[i + 1]
        if arg == "--output": output = value
        elif arg == "--write-out": write_out = value
        elif arg == "--request": method = value
        elif arg == "--data": data = value
        i += 2
        continue
    if not arg.startswith("-"):
        url = arg
    i += 1
with open(os.environ["FAKE_TOOL_LOG"], "a") as log:
    log.write(json.dumps(["curl", method, url, data]) + "\n")
path = urllib.parse.urlsplit(url).path
parts = path.split("/artifacts/", 1)[1].split("/")
reference = urllib.parse.unquote(parts[0])
def find(ref):
    for digest, artifact in state["artifacts"].items():
        if ref == digest or ref in artifact["tags"]:
            return digest, artifact
    return None, None
status, body = 404, {"errors": [{"code": "NOT_FOUND"}]}
digest, artifact = find(reference)
if len(parts) == 1 and method == "GET":
    if artifact:
        status = 200
        body = {"digest": digest, "annotations": artifact["manifest"].get("annotations", {}),
                "tags": [{"name": t} for t in artifact["tags"]]}
elif len(parts) == 2 and parts[1] == "tags" and method == "GET":
    if artifact:
        status, body = 200, [{"name": t} for t in artifact["tags"]]
elif len(parts) == 2 and parts[1] == "tags" and method == "POST":
    tag = json.loads(data)["name"]
    if find(tag)[1] is not None:
        status, body = 409, {"errors": [{"code": "CONFLICT"}]}
    elif artifact:
        artifact["tags"].append(tag)
        json.dump(state, open(state_path, "w"))
        status, body = 201, {}
json.dump(body, open(output, "w"))
sys.stdout.write(str(status) if write_out == "%{http_code}" else "")
'''

FAKE_ORAS = r'''#!/usr/bin/env python3
"""Fake ORAS: push (timestamped, like the real one), resolve, manifest fetch."""
import hashlib, json, os, sys, time
state_path = os.environ["FAKE_HARBOR_STATE"]
state = json.load(open(state_path))
args = sys.argv[1:]
with open(os.environ["FAKE_TOOL_LOG"], "a") as log:
    log.write(json.dumps(["oras"] + args) + "\n")
def find(ref):
    name, _, digest = ref.partition("@")
    if digest:
        return digest, state["artifacts"].get(digest)
    tag = ref.rsplit(":", 1)[1]
    for digest, artifact in state["artifacts"].items():
        if tag in artifact["tags"]:
            return digest, artifact
    return None, None
if args[0] == "push":
    annotations, positional, i = {}, [], 1
    while i < len(args):
        if args[i] == "--annotation":
            key, _, value = args[i + 1].partition("=")
            annotations[key] = value
            i += 2
        elif args[i].startswith("--"):
            i += 1
        else:
            positional.append(args[i])
            i += 1
    ref, layer = positional
    layer_file = layer.split(":", 1)[0]
    layer_digest = "sha256:" + hashlib.sha256(open(layer_file, "rb").read()).hexdigest()
    annotations["org.opencontainers.image.created"] = str(time.time_ns())
    manifest = {"schemaVersion": 2, "layers": [{"digest": layer_digest}], "annotations": annotations}
    digest = "sha256:" + hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    state["artifacts"][digest] = {"tags": [ref.rsplit(":", 1)[1]], "manifest": manifest}
    json.dump(state, open(state_path, "w"))
elif args[0] == "resolve":
    digest, artifact = find(args[1])
    if artifact is None:
        sys.exit(1)
    print(digest)
elif args[:2] == ["manifest", "fetch"]:
    digest, artifact = find(args[2])
    if artifact is None:
        sys.exit(1)
    print(json.dumps(artifact["manifest"]))
else:
    sys.exit(f"unsupported fake oras call: {args}")
'''


def git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "rho@example.invalid")
    git(path, "config", "user.name", "RHO Test")


def commit(path: Path, name: str) -> str:
    (path / "k8s").mkdir(exist_ok=True)
    (path / "k8s" / f"{name}.yaml").write_text(f"name: {name}\n", encoding="utf-8")
    git(path, "add", ".")
    git(path, "commit", "-qm", name)
    return git(path, "rev-parse", "HEAD")


@unittest.skipUnless(shutil.which("jq"), "jq is part of the ARC runner image the step runs on")
class ManifestPublishRetryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.step = step_script(MANIFEST, "Publish Argo CD OCI manifest bundle")
        cls.bin = Path(tempfile.mkdtemp(prefix="rho-retry-fakes-"))
        for name, source in {"curl": FAKE_CURL, "oras": FAKE_ORAS}.items():
            (cls.bin / name).write_text(source, encoding="utf-8")
            (cls.bin / name).chmod(0o755)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.bin)

    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="rho-retry-manifest-"))
        self.addCleanup(shutil.rmtree, self.work)
        self.repo = self.work / "repo"
        init_repo(self.repo)
        self.sha = commit(self.repo, "overlay")
        self.state = self.work / "harbor.json"
        self.state.write_text(json.dumps({"artifacts": {}}))
        self.log = self.work / "calls.ndjson"
        self.runs = 0

    def publish(self, version: str) -> subprocess.CompletedProcess[str]:
        self.runs += 1
        runner_temp = self.work / f"runner-{self.runs}"
        runner_temp.mkdir()
        self.log.write_text("")
        script = runner_temp / "step.sh"
        script.write_text(self.step, encoding="utf-8")
        return subprocess.run(
            ["bash", str(script)],
            cwd=self.repo,
            env={
                **os.environ,
                "PATH": f"{self.bin}:{os.environ['PATH']}",
                "FAKE_HARBOR_STATE": str(self.state),
                "FAKE_TOOL_LOG": str(self.log),
                "SOURCE_PATH": "k8s",
                "REGISTRY": "harbor.lan.e-dani.com",
                "REGISTRY_PROJECT": "homelab",
                "HARBOR_USER": "robot",
                "HARBOR_PASSWORD": "secret",
                "ARTIFACT_NAME": "caller",
                "VERSION": version,
                "SHA_TAG": f"sha-{self.sha[:12]}",
                "GITHUB_SHA": self.sha,
                "GITHUB_REPOSITORY": "example/caller",
                "GITHUB_RUN_ID": str(1000 + self.runs),
                "GITHUB_RUN_ATTEMPT": "1",
                "RUNNER_TEMP": str(runner_temp),
                "GITHUB_ENV": str(runner_temp / "github-env"),
            },
            capture_output=True,
            text=True,
        )

    def calls(self) -> list[list]:
        return [json.loads(line) for line in self.log.read_text().splitlines() if line]

    def tags(self) -> dict[str, list[str]]:
        state = json.loads(self.state.read_text())
        return {digest: artifact["tags"] for digest, artifact in state["artifacts"].items()}

    def test_retry_on_the_same_commit_reuses_the_published_bundle(self) -> None:
        first = self.publish("v1.0.0")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        # The deploy-branch push failed after this point in the measured runs;
        # the retry must neither push another manifest nor collide.
        retry = self.publish("v1.0.0")
        self.assertEqual(retry.returncode, 0, retry.stdout + retry.stderr)
        self.assertIn("Reusing manifest bundle", retry.stdout)
        self.assertFalse(any(call[:2] == ["oras", "push"] for call in self.calls()))
        released = [tags for tags in self.tags().values() if "v1.0.0" in tags]
        self.assertEqual(len(released), 1)
        self.assertIn(f"sha-{self.sha[:12]}", released[0])

    def test_retry_under_an_unused_version_tags_the_same_bundle(self) -> None:
        self.assertEqual(self.publish("v1.0.0").returncode, 0)
        retry = self.publish("v1.0.1")
        self.assertEqual(retry.returncode, 0, retry.stdout + retry.stderr)
        released = [tags for tags in self.tags().values() if "v1.0.1" in tags]
        self.assertEqual(len(released), 1)
        self.assertIn("v1.0.0", released[0])

    def test_version_owned_by_another_commit_fails_before_pushing(self) -> None:
        state = {"artifacts": {DIGEST_B: {"tags": ["v1.0.0", "sha-bbbbbbbbbbbb"], "manifest": {
            "annotations": {"org.opencontainers.image.revision": OTHER_REVISION}, "layers": []}}}}
        self.state.write_text(json.dumps(state))
        result = self.publish("v1.0.0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unused image_tag", result.stdout)
        self.assertFalse(any(call[:2] == ["oras", "push"] for call in self.calls()))
        self.assertFalse(any(call[:2] == ["curl", "POST"] for call in self.calls()))
        self.assertNotIn(f"sha-{self.sha[:12]}", sum(self.tags().values(), []))

    def test_sha_tag_bound_to_another_bundle_is_never_moved(self) -> None:
        state = {"artifacts": {DIGEST_A: {"tags": [f"sha-{self.sha[:12]}"], "manifest": {
            "annotations": {"org.opencontainers.image.revision": self.sha},
            "layers": [{"digest": DIGEST_B}]}}}}
        self.state.write_text(json.dumps(state))
        result = self.publish("v1.0.0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("never moved", result.stdout)
        self.assertEqual(self.tags(), {DIGEST_A: [f"sha-{self.sha[:12]}"]})


DEPLOY_BRANCH = "deploy/fixture"  # a trunk name would be refused by trunk-protecting push hooks


class LegacyPromotionTest(unittest.TestCase):
    """The legacy promotion must never rewind the deploy branch."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.step = step_script(MANIFEST, "Promote deploy branch directly (legacy compatibility)")

    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="rho-retry-promotion-"))
        self.addCleanup(shutil.rmtree, self.work)
        self.origin = self.work / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.origin)], check=True)
        self.author = self.work / "author"
        init_repo(self.author)
        git(self.author, "remote", "add", "origin", str(self.origin))
        self.base = commit(self.author, "base")
        git(self.author, "push", "-q", "origin", f"HEAD:refs/heads/{DEPLOY_BRANCH}")

    def checkout(self, revision: str) -> Path:
        """What actions/checkout with fetch-depth 0 leaves: all branches, detached HEAD."""
        runner = self.work / f"runner-{revision[:7]}"
        subprocess.run(["git", "clone", "-q", "--no-checkout", str(self.origin), str(runner)], check=True)
        git(runner, "checkout", "-q", "--detach", revision)
        return runner

    def promote(self, runner: Path) -> subprocess.CompletedProcess[str]:
        script = self.work / "promote.sh"
        script.write_text(self.step, encoding="utf-8")
        return subprocess.run(
            ["bash", str(script)],
            cwd=runner,
            env={**os.environ, "DEPLOY_BRANCH": DEPLOY_BRANCH, "GITHUB_SHA": git(runner, "rev-parse", "HEAD")},
            capture_output=True,
            text=True,
        )

    def deploy_tip(self) -> str:
        return git(self.origin, "rev-parse", f"refs/heads/{DEPLOY_BRANCH}")

    def test_release_of_the_deploy_tip_is_a_no_op(self) -> None:
        result = self.promote(self.checkout(self.base))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("nothing to promote", result.stdout)
        self.assertEqual(self.deploy_tip(), self.base)

    def test_deploy_branch_advanced_during_the_run_is_not_rewound(self) -> None:
        # Runs 36681403611 / 36705379093: deploy/prod advanced while the
        # release built; the push was rejected and the run went red.
        runner = self.checkout(self.base)
        advanced = commit(self.author, "merged-meanwhile")
        git(self.author, "push", "-q", "origin", f"HEAD:refs/heads/{DEPLOY_BRANCH}")
        result = self.promote(runner)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.deploy_tip(), advanced)

    def test_retry_of_an_older_run_is_not_rewound(self) -> None:
        # A retry re-checks out after the deploy branch advanced: a bare lease
        # would match the fresh tip and force-push the branch back.
        advanced = commit(self.author, "merged-later")
        git(self.author, "push", "-q", "origin", f"HEAD:refs/heads/{DEPLOY_BRANCH}")
        result = self.promote(self.checkout(self.base))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.deploy_tip(), advanced)

    def test_release_ahead_of_the_deploy_branch_is_promoted(self) -> None:
        release = commit(self.author, "release")
        git(self.author, "push", "-q", "origin", "HEAD:refs/heads/release-source")
        result = self.promote(self.checkout(release))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.deploy_tip(), release)

    def test_concurrent_advance_still_rejects_a_diverging_promotion(self) -> None:
        release = commit(self.author, "release")
        git(self.author, "push", "-q", "origin", "HEAD:refs/heads/release-source")
        runner = self.checkout(release)
        git(self.author, "checkout", "-q", "--detach", self.base)
        other = commit(self.author, "hotfix")
        git(self.author, "push", "-q", "origin", f"HEAD:refs/heads/{DEPLOY_BRANCH}")
        result = self.promote(runner)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.deploy_tip(), other)


if __name__ == "__main__":
    unittest.main()
