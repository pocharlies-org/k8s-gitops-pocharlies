from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ArcRunnerKs5PlacementTest(unittest.TestCase):
    def test_runner_selector_matches_the_ks5_pool(self) -> None:
        manifest = (ROOT / "infra/arc.yaml").read_text()
        runner_values = manifest.split("runnerScaleSetName: arc-k8s", 1)[1]
        runner_values = runner_values.split("tolerations:", 1)[0]

        self.assertIn("node-pool: ks5-nvme", runner_values)
        self.assertIn("kubernetes.io/arch: amd64", runner_values)
        self.assertNotIn("kubernetes.io/hostname:", runner_values)
        self.assertNotIn("workload: cpu", runner_values)

    def test_runner_pool_reserves_rollout_headroom(self) -> None:
        manifest = (ROOT / "infra/arc.yaml").read_text()
        self.assertIn("maxRunners: 4", manifest)

    def test_openclaw_has_dedicated_runner_pool(self) -> None:
        manifest = (ROOT / "infra/arc.yaml").read_text()
        openclaw_values = manifest.split("name: arc-openclaw", 1)[1]
        openclaw_values = openclaw_values.split("---", 1)[0]

        self.assertIn("https://github.com/pocharlies-org/k8s-openclaw-qwen36-pocharlies", openclaw_values)
        self.assertIn("maxRunners: 2", openclaw_values)
        self.assertIn("runnerScaleSetName: arc-openclaw", openclaw_values)
        self.assertIn("node-pool: ks5-nvme", openclaw_values)


if __name__ == "__main__":
    unittest.main()
