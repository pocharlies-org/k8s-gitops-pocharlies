from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER_IMAGE = "ghcr.io/actions/actions-runner:2.335.1@sha256:08c30b0a7105f64bddfc485d2487a22aa03932a791402393352fdf674bda2c29"
DIND_IMAGE = "docker.io/library/docker:29.7.1-dind@sha256:e8faad5a8dc5279dff929afc5449f2791736912fff9f99351d742db2fad01b4c"


class ArcRunnerKs5PlacementTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = (ROOT / "infra/arc.yaml").read_text()
        self.openclaw_values = self.manifest.split("name: arc-openclaw", 1)[1].split("---", 1)[0]
        self.shared_values = self.manifest.split("name: arc-k8s", 1)[1]

    def test_shared_runner_is_pinned_to_ks5_with_no_edge_fallback(self) -> None:
        """arc-k8s se queda en KS5 a proposito, sin caer a sauvage.

        Reescrito 2026-08-13. Este test exigia `values: [edge]` como fallback,
        pero el manifiesto lo habia quitado deliberadamente y nadie actualizo el
        test: los builds en sauvage compiten con el MinIO de un solo nodo de
        Harbor sobre md3 y hacen expirar subidas al registry que por lo demas
        estan sanas. La asimetria es intencionada — arc-openclaw si conserva el
        fallback — y la fija el test de abajo.
        """
        runner_values = self.shared_values.split("runnerScaleSetName: arc-k8s", 1)[1]
        runner_values = runner_values.split("tolerations:", 1)[0]

        self.assertIn("key: node-pool", runner_values)
        self.assertIn("kubernetes.io/arch: amd64", runner_values)
        self.assertIn("preferredDuringSchedulingIgnoredDuringExecution:", runner_values)
        self.assertIn("requiredDuringSchedulingIgnoredDuringExecution:", runner_values)
        self.assertIn("values: [ks5-nvme]", runner_values)
        self.assertNotIn("values: [edge]", runner_values)
        self.assertNotIn("kubernetes.io/hostname:", runner_values)
        self.assertNotIn("workload: cpu", runner_values)

    def test_edge_fallback_belongs_to_openclaw_only(self) -> None:
        """Solo arc-openclaw tolera y admite el nodo edge."""
        self.assertIn("key: role", self.openclaw_values)
        self.assertIn("value: edge", self.openclaw_values)
        self.assertIn("values: [edge]", self.openclaw_values)

        self.assertNotIn("key: role", self.shared_values)
        self.assertNotIn("value: edge", self.shared_values)

    def test_runner_pool_caps_backlog_drain_at_three(self) -> None:
        self.assertIn("maxRunners: 3", self.shared_values)
        self.assertNotIn("maxRunners: 4", self.manifest)

    def test_openclaw_has_dedicated_runner_pool(self) -> None:
        self.assertIn("https://github.com/pocharlies-org/k8s-openclaw-qwen36-pocharlies", self.openclaw_values)
        self.assertIn("maxRunners: 2", self.openclaw_values)
        self.assertIn("runnerScaleSetName: arc-openclaw", self.openclaw_values)
        self.assertIn("key: node-pool", self.openclaw_values)

    def test_openclaw_runner_is_unprivileged_and_dind_free(self) -> None:
        self.assertNotIn("containerMode:", self.openclaw_values)
        self.assertNotIn("name: dind", self.openclaw_values)
        self.assertNotIn("privileged: true", self.openclaw_values)
        self.assertIn(f"image: {RUNNER_IMAGE}", self.openclaw_values)
        self.assertIn("imagePullPolicy: IfNotPresent", self.openclaw_values)

    def test_all_runner_and_dind_images_are_digest_pinned(self) -> None:
        self.assertEqual(self.manifest.count(f"image: {RUNNER_IMAGE}"), 3)
        self.assertEqual(self.manifest.count(f"image: {DIND_IMAGE}"), 1)
        self.assertEqual(self.manifest.count("imagePullPolicy: IfNotPresent"), 4)
        self.assertNotIn("image: docker:dind", self.manifest)
        self.assertNotIn("image: ghcr.io/actions/actions-runner:2.335.1\n", self.manifest)

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

    def test_shared_runner_cpu_reservations_remain_bounded(self) -> None:
        externals = self.shared_values.split("name: init-dind-externals", 1)[1]
        externals = externals.split("name: dind", 1)[0]
        dind = self.shared_values.split("name: dind", 1)[1]
        dind = dind.split("name: runner", 1)[0]
        runner = self.shared_values.split("name: runner", 1)[1]

        self.assertIn('cpu: "5m"', externals)
        self.assertIn('cpu: "50m"', dind)
        self.assertIn('cpu: "100m"', runner)
        self.assertNotIn('cpu: "500m"', runner)

    def test_runner_pods_prefer_spread_but_tolerate_a_node_outage(self) -> None:
        for values in (self.openclaw_values, self.shared_values):
            pod_anti_affinity = values.split("podAntiAffinity:", 1)[1].split(
                "nodeSelector:", 1
            )[0]
            self.assertIn(
                "preferredDuringSchedulingIgnoredDuringExecution:", pod_anti_affinity
            )
            self.assertIn("weight: 100", pod_anti_affinity)
            self.assertNotIn(
                "requiredDuringSchedulingIgnoredDuringExecution:", pod_anti_affinity
            )
            self.assertIn(
                "app.kubernetes.io/part-of: gha-runner-scale-set", pod_anti_affinity
            )
            self.assertIn(
                "topologyKey: kubernetes.io/hostname", pod_anti_affinity
            )

    def test_real_render_gate_is_part_of_ci(self) -> None:
        workflow = (ROOT / ".github/workflows/reusable-ci.yml").read_text()
        verifier = ROOT / "scripts/verify_arc_runner_render.sh"
        self.assertTrue(verifier.is_file())
        self.assertIn("scripts/verify_arc_runner_render.sh", workflow)


if __name__ == "__main__":
    unittest.main()
