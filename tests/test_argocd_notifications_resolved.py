"""SC-5249: el camino de vuelta de las alertas de Keep (SC-5223) no puede romperse en silencio.

Dos cosas se guardan aquí, las dos medidas en vivo el 10-11-2026:

1. Que cada `template.*` y `trigger.*` del bloque `notifications` sea YAML válido. El notifications-controller
   los parsea todos juntos: uno solo mal formado (un `description:` con `: ` sin comillas) tumba el config
   ENTERO y ArgoCD deja de emitir también los `firing` — sin alerta, sin incidente y sin error en el sync,
   porque el fallo es del controller al leer el ConfigMap.
2. Que el resolved sea espejo del firing: mismo `name` y misma `fingerprint`. Keep empareja por huella y la
   regla `argocd-app-degraded` (k8s-observability-pocharlies) cierra el incidente con `resolveOn: all_resolved`,
   agrupando por `app`. Un `fingerprint` que diverja deja la alerta firing para siempre (SC-5203).
"""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

# (plantilla de firing, plantilla de resolved) — el resolved se empareja con el firing por huella.
PARES = [
    ("keep-health-degraded", "keep-health-degraded-resolved"),
    ("keep-sync-failed", "keep-sync-failed-resolved"),
]


def _notifications() -> dict:
    return yaml.safe_load((ROOT / "argocd/values.yaml").read_text())["notifications"]


def _lineas(body: str) -> list[str]:
    """El cuerpo del webhook sin las líneas que SÍ cambian entre firing y resolved. Comparar línea a
    línea es más estricto que comparar claves: `fingerprint` y `labels` ocupan varias líneas y un cambio
    suyo tiene que hacer fallar el test."""
    return [ln.strip() for ln in body.splitlines()
            if ln.strip() and '"status":' not in ln and '"description":' not in ln]


class ArgocdNotificationsParseableTest(unittest.TestCase):
    def test_every_template_and_trigger_is_valid_yaml(self) -> None:
        n = _notifications()
        for bloque in ("templates", "triggers"):
            for clave, valor in n[bloque].items():
                with self.subTest(key=clave):
                    try:
                        yaml.safe_load(valor)
                    except yaml.YAMLError as exc:
                        self.fail(f"{clave} no es YAML válido y deja el notifications-cm sin cargar: {exc}")

    def test_subscriptions_only_reference_existing_triggers(self) -> None:
        n = _notifications()
        declarados = {k[len("trigger."):] for k in n["triggers"]}
        for sub in n["subscriptions"]:
            for trig in sub["triggers"]:
                self.assertIn(trig, declarados, f"suscripción a un trigger inexistente: {trig}")


class ArgocdNotificationsResolvedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.notifications = _notifications()

    def _webhook(self, template: str) -> dict:
        return yaml.safe_load(self.notifications["templates"][f"template.{template}"])["webhook"]["keep"]

    def test_resolved_is_the_mirror_of_firing(self) -> None:
        for firing_tpl, resolved_tpl in PARES:
            with self.subTest(template=resolved_tpl):
                firing, resolved = self._webhook(firing_tpl), self._webhook(resolved_tpl)
                self.assertEqual(firing["method"], resolved["method"])
                self.assertEqual(firing["path"], resolved["path"])
                self.assertEqual(_lineas(firing["body"]), _lineas(resolved["body"]),
                                 f"{resolved_tpl} debe ser espejo de {firing_tpl}: mismo name, mismo "
                                 "fingerprint y mismos labels (Keep empareja el resolved por huella)")
                self.assertIn('"status": "firing"', firing["body"])
                self.assertIn('"status": "resolved"', resolved["body"])
                self.assertIn('"source": ["argocd"]', resolved["body"],
                              "source como lista: sin ella Keep descarta el evento (lane sre-devops, INFRA-405)")

    def test_resolved_trigger_sends_both_and_is_subscribed_to_keep(self) -> None:
        trigger = yaml.safe_load(self.notifications["triggers"]["trigger.on-sync-resolved"])[0]
        self.assertEqual(sorted(trigger["send"]), sorted(t for _, t in PARES))
        self.assertIn("oncePer", trigger,
                      "sin oncePer el dedup del motor se traga el resolved y la alerta queda firing (SC-5223)")
        keep = [s for s in self.notifications["subscriptions"] if s["recipients"] == ["keep"]][0]
        self.assertIn("on-sync-resolved", keep["triggers"])
        firing_when = yaml.safe_load(self.notifications["triggers"]["trigger.on-sync-failed"])[0]["when"]
        self.assertNotEqual(trigger["when"], firing_when,
                            "el resolved no puede disparar con la condición del firing")


class ArgocdNotificationsSyncPausedTest(unittest.TestCase):
    """(SC-5453) El hallazgo de app con el sync pausado (OutOfSync sin automated) no puede
    romperse en silencio: mismo espejo firing/resolved que las de fallo, disparado solo
    cuando la app no se auto-cura, y excluyendo las apps que declaran sync manual a propósito."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.notifications = _notifications()

    def _webhook(self, template: str) -> dict:
        return yaml.safe_load(self.notifications["templates"][f"template.{template}"])["webhook"]["keep"]

    def test_paused_resolved_is_the_mirror_of_firing(self) -> None:
        firing, resolved = self._webhook("keep-sync-paused"), self._webhook("keep-sync-paused-resolved")
        self.assertEqual(firing["path"], resolved["path"])
        self.assertEqual(_lineas(firing["body"]), _lineas(resolved["body"]),
                         "keep-sync-paused-resolved debe ser espejo de keep-sync-paused: mismo name y "
                         "fingerprint (Keep empareja el resolved por huella)")
        self.assertIn('"name": "ArgoCDAppSyncPaused"', firing["body"])
        self.assertIn('"status": "firing"', firing["body"])
        self.assertIn('"status": "resolved"', resolved["body"])
        self.assertIn('"source": ["argocd"]', resolved["body"],
                      "source como lista: sin ella Keep descarta el evento (INFRA-405)")

    def test_paused_trigger_condition_excludes_manual_sync_apps(self) -> None:
        trigger = yaml.safe_load(self.notifications["triggers"]["trigger.on-sync-paused"])[0]
        when = trigger["when"]
        self.assertIn("OutOfSync", when)
        self.assertIn("app.spec.syncPolicy.automated == nil", when)
        # root (app-of-apps, sync manual) y shopify-back-in-stock (apps-disabled) declaran
        # sync manual: sin excluirlas abrirían un incidente PAUSA permanente y falso.
        self.assertIn("root", when)
        self.assertIn("shopify-back-in-stock", when)

    def test_paused_triggers_are_subscribed_to_keep(self) -> None:
        keep = [s for s in self.notifications["subscriptions"] if s["recipients"] == ["keep"]][0]
        self.assertIn("on-sync-paused", keep["triggers"])
        self.assertIn("on-sync-paused-resolved", keep["triggers"])


if __name__ == "__main__":
    unittest.main()
