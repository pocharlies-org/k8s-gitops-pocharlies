"""INFRA-549 (P3 de INFRA-400), criterio C3: el dimensionado de arc-k8s se toca
solo con una medida detras, citada en un comentario fechado en la propia
Application. Este test es la puerta: quien cambie maxRunners sin comentario
cerrando el bloque, corta CI.

Las cifras de referencia (INFRA-547, docs/ci-queue-diagnosis-2026-10.md) son
provisionales a nivel de run hasta su remedicion exacta: el valor se sostiene
en 16 y lo sube solo una rafaga limpia sobre ks5 (<=70 % CPU, readyz passed,
etcd sin slow fdatasync) con INFRA-123 cerrado.
"""

from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATED_COMMENT = re.compile(r"#\s*\d{4}-\d{2}-\d{2}\s+\S+")
ISSUE_KEY = re.compile(r"\b[A-Z]+-\d+\b")


def arc_application(name: str) -> dict:
    documents = yaml.safe_load_all(
        (ROOT / "infra/arc.yaml").read_text(encoding="utf-8")
    )
    for document in documents:
        if (
            isinstance(document, dict)
            and document.get("kind") == "Application"
            and document["metadata"]["name"] == name
        ):
            return document
    raise AssertionError(f"Application {name} not found in infra/arc.yaml")


class ArcK8sSizingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.application = arc_application("arc-k8s")
        self.values_text = self.application["spec"]["source"]["helm"]["values"]
        self.values = yaml.safe_load(self.values_text)

    def test_max_runners_is_an_int(self) -> None:
        self.assertIsInstance(self.values["maxRunners"], int)
        self.assertGreater(self.values["maxRunners"], 0)

    def test_min_runners_is_defined(self) -> None:
        self.assertIn("minRunners", self.values)
        self.assertIsInstance(self.values["minRunners"], int)
        self.assertLessEqual(self.values["minRunners"], self.values["maxRunners"])

    def test_max_runners_carries_a_dated_comment(self) -> None:
        """El bloque de comentarios inmediatamente anterior a maxRunners tiene
        una fecha y una clave de ticket: la medida que justifica el numero."""
        lines = self.values_text.splitlines()
        index = next(
            i for i, line in enumerate(lines) if re.match(r"\s*maxRunners:", line)
        )
        block: list[str] = []
        for offset in range(1, index + 1):
            line = lines[index - offset].strip()
            if not line:
                break
            if not line.startswith("#"):
                break
            block.append(line)
        self.assertTrue(
            block,
            "maxRunners changed without a dated comment citing the "
            "measurement (INFRA-549 / criterio C3)",
        )
        joined = "\n".join(block)
        self.assertTrue(
            DATED_COMMENT.search(joined),
            "the comment above maxRunners must start a block with a date "
            "(# YYYY-MM-DD <who>)",
        )
        self.assertTrue(
            ISSUE_KEY.search(joined),
            "the comment above maxRunners must cite the ticket with the "
            "measurement (e.g. INFRA-547)",
        )

    def test_sizing_cites_the_queue_measurement(self) -> None:
        """El comentario cita INFRA-547, la fuente de las cifras de la cola."""
        index = self.values_text.index("maxRunners:")
        self.assertIn("INFRA-547", self.values_text[:index])

    def test_edge_node_stays_out_of_the_shared_pool(self) -> None:
        """La rafaga no se lanza contra sauvage: sigue sin tolerar role=edge."""
        values = yaml.safe_load(
            arc_application("arc-openclaw")["spec"]["source"]["helm"]["values"]
        )
        self.assertTrue(values["template"]["spec"]["tolerations"])
        shared_tolerations = self.values["template"]["spec"]["tolerations"]
        self.assertNotIn(
            "edge",
            [entry.get("value") for entry in shared_tolerations],
        )


if __name__ == "__main__":
    unittest.main()
