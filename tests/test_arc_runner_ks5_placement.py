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

    def test_shared_runner_has_free_amd64_scheduling(self) -> None:
        """arc-k8s se coloca en cualquier nodo amd64 SANO — sin nodeAffinity.

        Solo hay nodeAffinity PREFERIDA (sauvage como desborde, ver
        test_shared_pool_uses_edge_only_as_overflow). Este test defiende que
        nadie vuelva a meter un pinning duro a un nodo concreto.
        """
        runner_values = self.shared_values.split("runnerScaleSetName: arc-k8s", 1)[1]
        runner_values = runner_values.split("tolerations:", 1)[0]

        self.assertIn("kubernetes.io/arch: amd64", runner_values)
        self.assertIn("preferredDuringSchedulingIgnoredDuringExecution:", runner_values)
        self.assertNotIn("key: node-pool", runner_values)
        self.assertNotIn("requiredDuringSchedulingIgnoredDuringExecution:", runner_values)
        self.assertNotIn("values: [ks5-nvme]", runner_values)
        self.assertNotIn("kubernetes.io/hostname:", runner_values)
        self.assertNotIn("workload: cpu", runner_values)

    def test_edge_node_is_tolerated_by_openclaw(self) -> None:
        """arc-openclaw conserva su fallback a edge (su carga es otra)."""
        self.assertIn("key: role", self.openclaw_values)
        self.assertIn("value: edge", self.openclaw_values)
        self.assertIn("values: [edge]", self.openclaw_values)

    def test_shared_pool_uses_edge_only_as_overflow(self) -> None:
        """arc-k8s tolera role=edge, pero sauvage es solo DESBORDE.

        Deroga el "NO tolera edge" del 22-09 (md3 al 100 %: un runner ahi se
        arrastra). Desde el 24-09 el pool tiene 16 plazas y la decision es que
        el scheduler reparta por todo el cluster; para que sauvage solo entre
        cuando los demas van cargados, la toleration va con una nodeAffinity
        PREFERIDA en contra de role=edge (nunca required: eso lo dejaria fuera).
        """
        runner_tolerations = self.shared_values.split("tolerations:", 1)[1]
        runner_tolerations = runner_tolerations.split("initContainers:", 1)[0]
        self.assertIn("key: role", runner_tolerations)
        self.assertIn("value: edge", runner_tolerations)
        self.assertIn("key: pool", runner_tolerations)

        affinity = self.shared_values.split("affinity:", 1)[1].split("podAntiAffinity:", 1)[0]
        self.assertIn("nodeAffinity:", affinity)
        self.assertIn("preferredDuringSchedulingIgnoredDuringExecution:", affinity)
        self.assertIn("operator: NotIn", affinity)
        self.assertIn("values: [edge]", affinity)
        self.assertNotIn("requiredDuringSchedulingIgnoredDuringExecution:", affinity)

    def test_runner_pool_caps_backlog_drain_at_sixteen(self) -> None:
        """16 plazas repartidas por el scheduler; ver el comentario en infra/arc.yaml."""
        self.assertIn("maxRunners: 16", self.shared_values)
        self.assertNotIn("maxRunners: 8", self.shared_values)
        self.assertNotIn("maxRunners: 6", self.shared_values)
        self.assertNotIn("maxRunners: 3", self.shared_values)
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
        # 2026-09-16: uploads de registry en paralelo (fuera el cap secuencial).
        self.assertNotIn("--max-concurrent-uploads", self.shared_values)
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

    def test_dind_bridge_mtu_matches_the_pod_network(self) -> None:
        """El bridge de DinD baja a 1230 para no exceder la MTU del pod.

        2026-09-17: dockerd deja su bridge en 1500 salvo que se le diga otra
        cosa, pero la red de pods va a 1230 (overhead de tailnet/WireGuard).
        El contenedor de build emitia tramas que la ruta del pod no podia
        cursar: la conexion abre y llegan las cabeceras — asi que las
        peticiones pequenas parecian sanas — y cualquier transferencia grande
        se quedaba colgada hasta agotar el timeout del step. Solo se
        manifestaba en los nodos cuyo egress no lo rescata por PMTU
        discovery, por lo que parecia un runner inestable y no un fallo de
        configuracion: 30 min colgado en `apt-get update` sobre ks5 y build
        limpio sobre sauvage, con el mismo commit.
        """
        dind_values = self.shared_values.split("name: dind", 1)[1]
        dind_values = dind_values.split("env:", 1)[0]

        self.assertIn("--mtu=1230", dind_values)

    def test_real_render_gate_is_part_of_ci(self) -> None:
        workflow = (ROOT / ".github/workflows/reusable-ci.yml").read_text()
        verifier = ROOT / "scripts/verify_arc_runner_render.sh"
        self.assertTrue(verifier.is_file())
        self.assertIn("scripts/verify_arc_runner_render.sh", workflow)


if __name__ == "__main__":
    unittest.main()
