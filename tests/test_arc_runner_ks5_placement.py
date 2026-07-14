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


if __name__ == "__main__":
    unittest.main()
