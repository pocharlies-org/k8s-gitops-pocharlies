from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ArcRunnerKs5PlacementTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = (ROOT / "infra/arc.yaml").read_text()
        self.openclaw_values = self.manifest.split("name: arc-openclaw", 1)[1].split("---", 1)[0]
        self.shared_values = self.manifest.split("name: arc-k8s", 1)[1]

    def test_runner_selector_matches_the_ks5_pool(self) -> None:
        runner_values = self.shared_values.split("runnerScaleSetName: arc-k8s", 1)[1]
        runner_values = runner_values.split("tolerations:", 1)[0]

        self.assertIn("node-pool: ks5-nvme", runner_values)
        self.assertIn("kubernetes.io/arch: amd64", runner_values)
        self.assertNotIn("kubernetes.io/hostname:", runner_values)
        self.assertNotIn("workload: cpu", runner_values)

    def test_runner_pool_reserves_rollout_headroom(self) -> None:
        self.assertIn("maxRunners: 2", self.shared_values)
        self.assertNotIn("maxRunners: 4", self.manifest)

    def test_openclaw_has_dedicated_runner_pool(self) -> None:
        self.assertIn("https://github.com/pocharlies-org/k8s-openclaw-qwen36-pocharlies", self.openclaw_values)
        self.assertIn("maxRunners: 2", self.openclaw_values)
        self.assertIn("runnerScaleSetName: arc-openclaw", self.openclaw_values)
        self.assertIn("node-pool: ks5-nvme", self.openclaw_values)

    def test_openclaw_runner_is_unprivileged_and_dind_free(self) -> None:
        self.assertNotIn("containerMode:", self.openclaw_values)
        self.assertNotIn("name: dind", self.openclaw_values)
        self.assertNotIn("privileged: true", self.openclaw_values)

    def test_shared_dind_is_a_resource_bounded_restartable_init_container(self) -> None:
        self.assertNotIn("containerMode:", self.shared_values)
        self.assertIn("initContainers:", self.shared_values)
        self.assertIn('command: ["cp"]', self.shared_values)
        self.assertIn(
            'args: ["-r", "/home/runner/externals/.", "/home/runner/tmpDir/"]',
            self.shared_values,
        )
        self.assertNotIn(
            'command: ["cp", "-r", "/home/runner/externals/.", "/home/runner/tmpDir/"]',
            self.shared_values,
        )
        self.assertIn("name: dind", self.shared_values)
        self.assertIn("restartPolicy: Always", self.shared_values)
        self.assertIn('cpu: "50m"', self.shared_values)
        self.assertIn('memory: "512Mi"', self.shared_values)

    def test_shared_runner_cpu_reservations_fit_two_anti_affine_pods(self) -> None:
        externals = self.shared_values.split("name: init-dind-externals", 1)[1]
        externals = externals.split("name: dind", 1)[0]
        dind = self.shared_values.split("name: dind", 1)[1]
        dind = dind.split("name: runner", 1)[0]
        runner = self.shared_values.split("name: runner", 1)[1]

        self.assertIn('cpu: "5m"', externals)
        self.assertIn('cpu: "50m"', dind)
        self.assertIn('cpu: "100m"', runner)
        self.assertNotIn('cpu: "500m"', runner)

    def test_runner_pods_cannot_co_locate_on_one_ks5_host(self) -> None:
        for values in (self.openclaw_values, self.shared_values):
            self.assertIn("requiredDuringSchedulingIgnoredDuringExecution:", values)
            self.assertIn("app.kubernetes.io/part-of: gha-runner-scale-set", values)
            self.assertIn("topologyKey: kubernetes.io/hostname", values)

    def test_real_render_gate_is_part_of_ci(self) -> None:
        workflow = (ROOT / ".github/workflows/reusable-ci.yml").read_text()
        verifier = ROOT / "scripts/verify_arc_runner_render.sh"
        self.assertTrue(verifier.is_file())
        self.assertIn("scripts/verify_arc_runner_render.sh", workflow)


if __name__ == "__main__":
    unittest.main()
