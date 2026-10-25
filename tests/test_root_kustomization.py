import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
# SC-2956: apps/analisis.yaml llegó a deploy/prod sin entrada aquí y root nunca creó la Application.


class RootKustomizationTest(unittest.TestCase):
    def test_every_app_is_listed(self) -> None:
        listed = set(yaml.safe_load((ROOT / "kustomization.yaml").read_text(encoding="utf-8"))["resources"])
        apps = {f"apps/{p.name}" for p in (ROOT / "apps").glob("*.yaml")}
        self.assertEqual(sorted(apps - listed), [])


if __name__ == "__main__":
    unittest.main()
