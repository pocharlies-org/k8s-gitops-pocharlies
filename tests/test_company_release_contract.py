"""SC-3961: exercise the prepared-context caller gate without credentials or a runner."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / '.github/workflows/reusable-release.yml').read_text()
CALLER = (ROOT / 'templates/ci/release-company-runtime.yml').read_text()


class CompanyReleaseTests(unittest.TestCase):
    def gate(self, **changes):
        block = WORKFLOW.split('- name: Validate prepared company context caller', 1)[1]
        code = block.split("python3 -I - <<'PY'\n", 1)[1].split('\n          PY', 1)[0]
        import textwrap
        code = textwrap.dedent(code)
        env = {**os.environ, 'GITHUB_REPOSITORY': 'pocharlies-org/x86-host-runtime-pocharlies',
               'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
               'GITHUB_SHA': 'a' * 40, 'ARTIFACT': 'company-runtime-context-' + 'a' * 40,
               'REGISTRY': 'harbor.lan.e-dani.com', 'PROJECT': 'homelab',
               'IMAGES': json.dumps([{'name': 'company-runtime', 'context': 'company-release-context',
                                     'dockerfile': 'company-release-context/Dockerfile'}]), **changes}
        return subprocess.run([sys.executable, '-I', '-c', code], env=env,
                              capture_output=True, timeout=10).returncode

    def test_only_exact_company_main_dispatch_and_image_is_allowed(self):
        self.assertEqual(self.gate(), 0)
        for key, value in [('GITHUB_REPOSITORY', 'other/repo'), ('GITHUB_REF', 'refs/heads/test'),
                           ('GITHUB_EVENT_NAME', 'pull_request'), ('ARTIFACT', 'another-run'),
                           ('REGISTRY', 'other.invalid'), ('PROJECT', 'other'), ('IMAGES', '[]')]:
            with self.subTest(key=key):
                self.assertNotEqual(self.gate(**{key: value}), 0)

    def test_default_path_stays_optional_and_archive_is_bounded_to_same_run(self):
        self.assertIn('company_context_artifact:', WORKFLOW)
        self.assertIn('default: ""', WORKFLOW)
        self.assertIn('actions/download-artifact@634f93cb2916e3fdff6788551b99b062d0335ce0', WORKFLOW)
        self.assertNotIn('run-id:', WORKFLOW)
        self.assertNotIn('github-token:', WORKFLOW)
        self.assertIn("archive.extractall(root, filter='data')", WORKFLOW)
        self.assertIn("not (entry.isfile() or entry.isdir())", WORKFLOW)
        self.assertIn("release['runtime_commit'] == os.environ['GITHUB_SHA']", WORKFLOW)
        self.assertIn("assert (root / name).read_bytes() == content", WORKFLOW)
        self.assertLess(WORKFLOW.index('Verify prepared company source binding'),
                        WORKFLOW.index('- uses: docker/login-action@'))

    def test_rebuilt_candidate_is_smoked_before_first_push(self):
        build = WORKFLOW.index('while IFS=', WORKFLOW.index('RELEASE_PREFLIGHT_DECISION'))
        scan = WORKFLOW.index('trivy image', build)
        smoke = WORKFLOW.index('python3 -I company-release-context/smoke.py', scan)
        push = WORKFLOW.index('push_image "$candidate_ref"', smoke)
        self.assertLess(scan, smoke)
        self.assertLess(smoke, push)
        self.assertIn("docker image inspect --format '{{.Id}}'", WORKFLOW)
        self.assertNotIn('smoke_command:', WORKFLOW)

    def test_caller_is_manual_fixed_destination_and_separates_credentials(self):
        self.assertIn('workflow_dispatch:', CALLER)
        self.assertNotIn('  push:', CALLER)
        self.assertNotIn('  pull_request:', CALLER)
        self.assertNotIn('inputs:', CALLER)
        context, release = CALLER.split('\n  release:', 1)
        self.assertNotIn('HARBOR_', context)
        self.assertNotIn('FRAMEWORK_REPO_TOKEN', release)
        self.assertNotIn('secrets: inherit', CALLER)
        self.assertIn('id-token: write', release)
        self.assertNotIn('contents: write', CALLER)
        self.assertIn('registry_project: homelab', release)
        self.assertIn('"name":"company-runtime"', release)
        self.assertIn('company-release-transfer/context.tar.gz', context)
        self.assertIn('retention-days: 1', context)
        self.assertNotIn('kubectl', CALLER)
        import re
        reference = re.search(r'reusable-release\.yml@([0-9a-f]{40})', release)
        self.assertIsNotNone(reference)
        self.assertNotEqual(reference.group(1), '0' * 40)
        self.assertIn('NOT approved', release)


if __name__ == '__main__':
    unittest.main()
