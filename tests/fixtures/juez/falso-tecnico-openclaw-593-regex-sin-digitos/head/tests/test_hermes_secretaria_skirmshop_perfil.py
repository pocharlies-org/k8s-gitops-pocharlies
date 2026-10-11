"""INFRA-492 (04-10-2026): alta de la quinta secretaria, `secretaria-skirmshop`, por config.

Qué fija este fichero y por qué existe: el perfil es de SOLO LECTURA por diseño (C4 de la épica:
resumen de avisos de la tienda; no ejecuta Acciones de pago ni escribe en Shopify/Picqer). Cada
herramienta de su lista `servers` es una regla ABIERTA (sin `$GATEWAY_WRITE`) en la
`mcpAuthorization` de k8s-agentgateway-pocharlies (`k8s/base/agentgateway-config.yaml`, medido
04-10-2026 en origin/main): en el gateway no hay ninguna puerta de escritura que el perfil pueda
abrir. Si alguien añade una tool gated aquí, este test la para antes del merge.

Dos cosas más, fijadas a propósito:
- La ruta de bot lleva `thread_id` exacto (topic «Secretaria Skirmshop» 9088, creado por qa con
  `social_manage_forum`, SC-1713): una entrada sin thread en un grupo-foro se come todos los
  topics (patrón `studio`) y secuestraría Pocharlies Operations.
- La matriz `empresa.permisos` sigue default-deny: la quinta secretaria tiene su fila (puede
  delegar a security y a la secretaria de trabajo) y NO aparece en ninguna otra fila — quién
  puede delegarle a ella lo fija security (INFRA-479).
"""
import json
import re

import pytest
import yaml

from _hermes_seed import VALUES, seed

PERFIL = "secretaria-skirmshop"
CHAT_OPS = "-1004409526898"
SECRETARIAS = ("secretaria", "secretaria-dani", "secretaria-leila", "secretaria-casa", PERFIL)

# Las reglas abiertas (sin GATEWAY_WRITE) por ruta, medidas en origin/main del repo del gateway.
LECTURAS_ABIERTAS = {
    "shopify": {"get-products", "get-products-by-collection", "get-products-by-ids",
                "get-variants-by-ids", "get-customers", "get-orders", "get-order",
                "get-collections", "get-shop", "get-shop-details"},
    "picqer": {"picqer_webshop_orders", "picqer_warehouses", "picqer_users",
               "picqer_shipments", "picqer_stats", "picqer_reference_data"},
    # El plano READ de skirmshop-plugins: `skirmshop_plugins_get` vive solo en el plano ADMIN
    # (gated agentgateway-write) — por eso no está aquí ni en la lista del perfil.
    "skirmshop-plugins": {"skirmshop_plugins_list", "skirmshop_plugins_describe",
                          "labels_rate_quote", "labels_correos_fuel_surcharge",
                          "labels_shipment_status"},
    "workspace": {"gmail_get_profile", "gmail_search", "gmail_search_ids", "gmail_get_message",
                  "gmail_batch_get_messages", "gmail_get_thread", "gmail_batch_get_threads",
                  "gmail_get_attachment", "gmail_list_labels", "gmail_list_drafts", "gmail_get_draft",
                  "calendar_list_events", "drive_search", "drive_get_file"},
}
# INFRA-641/644: lo ÚNICO de escritura que gana el perfil: crear y editar borradores de correo, por el rol propio
# agentgateway-write:workspace-borrador de su client (INFRA-642; security INFRA-640 lo aprobó). Nada que envíe, borre,
# archive ni etiquete: la tarjeta de enviar la decide Dani.
ESCRITURA_BORRADOR = {"gmail_create_draft", "gmail_update_draft"}


def _spec():
    return VALUES["profiles"][PERFIL]


def test_el_perfil_existe_con_frenos_y_fallback_de_secretaria():
    spec = _spec()
    assert spec["frenos"] == "secretaria"
    assert spec["fallbackModel"] == VALUES["profiles"]["secretaria"]["fallbackModel"]
    assert spec["apiServerKeyEnv"] == "HERMES_API_SERVER_KEY_SECRETARIA_SKIRMSHOP"


def test_servers_solo_lectura_sin_ningun_plano_de_escritura():
    """C4: ni una tool gated `$GATEWAY_WRITE` en el gateway. Cada ruta de la lista está en el
    plano de lectura y cada tool es una regla abierta medida en agentgateway-config.yaml."""
    servers = _spec()["servers"]
    assert set(servers) <= {"brain", "workspace", "shopify", "picqer", "skirmshop-plugins"}, servers
    for ruta, tools in servers.items():
        abiertas = LECTURAS_ABIERTAS.get(ruta)
        if abiertas is not None:
            permitidas = abiertas | (ESCRITURA_BORRADOR if ruta == "workspace" else set())
            assert set(tools) <= permitidas, (ruta, sorted(set(tools) - permitidas))
    assert "skirmshop_plugins_get" not in servers.get("skirmshop-plugins", [])
    assert "calendar_create_event" not in servers.get("workspace", [])
    assert "social" not in servers  # no escribe a personas


def test_brain_instancia_skirmshop_no_personal():
    """C3: la memoria de la tienda. Sin la entrada explícita herdaría `claude-personal` (trabajo
    de los roles); `personal` sería un error (es la memoria de casa)."""
    assert VALUES["brainMemory"]["instanceByProfile"][PERFIL] == "skirmshop"


def test_ruta_webhook_hmac_v2_al_mismo_patron_que_sus_hermanas():
    r = VALUES["webhook"]["routes"][PERFIL]
    assert r["profile"] == PERFIL
    assert r["deliver"] == "telegram"
    assert r["deliver_extra"]["chat_id"] == CHAT_OPS
    assert r["rate_limit"] == 20
    # toolsets = las rutas MCP del perfil + lo de plataforma; ninguna de escritura
    assert "social" not in r["toolsets"] and "shopify-admin" not in r["toolsets"]
    assert set(r["toolsets"]) <= {"hermes-telegram", "workspace", "brain", "cronjob",
                                  "shopify", "picqer", "skirmshop-plugins"}


def test_ruta_de_bot_a_su_topic_con_thread_exacto():
    """Quinta ruta de chat de secretaria. Con `thread_id` a propósito: una entrada sin thread en
    un grupo-foro enruta TODOS sus topics (patrón `studio`) y secuestraría Pocharlies Operations.
    El topic «Secretaria Skirmshop» (9088) lo creó qa con `social_manage_forum` (SC-1713)."""
    rutas = [x for x in VALUES["routes"] if x.get("profile") == PERFIL]
    assert len(rutas) == 2        # DGX-746: la de siempre y la de su topic «Correo» (9775), ambas con thread exacto
    r = next(x for x in rutas if x["name"] == PERFIL)
    assert r["chat_id"] == CHAT_OPS and r["thread_id"] == "9088" and r["platform"] == "telegram"
    # y la ruta webhook entrega en el MISMO topic
    assert VALUES["webhook"]["routes"][PERFIL]["deliver_extra"] == {"chat_id": CHAT_OPS,
                                                                    "thread_id": "9088"}
    # cinco secretarias con ruta de chat (la regla de las cinco, INFRA-495), cada una con sus dos topics (DGX-746)
    assert sorted(x["profile"] for x in VALUES["routes"]
                  if str(x.get("profile", "")).startswith("secretaria")) == sorted(SECRETARIAS * 2)


def test_heredad_y_soul_sin_duplicar_el_oficio():
    assert VALUES["herencia"]["hereda"][PERFIL] == ["oficio-secretaria", "recibir-encargo", "correo-borrador",
                                                    "borrador-skirmshop", "tono-skirmshop"]
    assert PERFIL in VALUES["souls"]
    cabecera = VALUES["herencia"]["bloques"]["oficio-secretaria"].splitlines()[0].strip()
    assert cabecera not in VALUES["souls"][PERFIL]


def test_empresa_destino_nuevo_matriz_default_deny_intacta():
    e = VALUES["empresa"]
    assert e["destinos"][PERFIL] == {"ruta": PERFIL}
    assert PERFIL in e["permisos"]  # toda fila debe existir (test_hermes_empresa_delegacion)
    assert set(e["permisos"][PERFIL]) <= {"security", "secretaria"}
    # default-deny: NADIE la alcanza todavía — la matriz la fija security
    for perfil, fila in e["permisos"].items():
        if perfil != PERFIL:
            assert PERFIL not in fila, perfil


def test_no_en_pagos():
    """Sin escritura ni compras: la compuerta de pago no se registra en este perfil."""
    assert PERFIL not in VALUES["pagos"]["perfiles"]


def test_el_seed_siembra_ruta_webhook_con_secreto_y_soul_heredado(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_WEBHOOK_SECRET", "s" * 48)
    monkeypatch.setenv("HERMES_WEBHOOK_JSON", json.dumps(
        {"port": VALUES["webhook"]["port"], "routes": VALUES["webhook"]["routes"]}))
    home = seed(str(tmp_path / "h"))
    rutas = json.loads((home / "webhook_subscriptions.json").read_text())
    assert rutas[PERFIL]["profile"] == PERFIL
    assert rutas[PERFIL]["secret"] == "s" * 48
    cfg = yaml.safe_load((home / "profiles" / PERFIL / "config.yaml").read_text())
    assert cfg["approvals"]["mode"] == "off" and cfg["approvals"]["deny"]
    servers = cfg["mcp_servers"]
    assert set(servers) <= {"brain", "workspace", "shopify", "picqer", "skirmshop-plugins"}
    soul = (home / "profiles" / PERFIL / "SOUL.md").read_text()
    for bloque in ("## La empresa", "## El oficio de secretaria", "## Recibir encargos",
                   "## Tono y límites de la secretaria de la tienda"):
        assert bloque in soul, bloque


def test_soul_no_promete_escritura_ni_pago_ni_delegacion_que_la_matriz_no_da(monkeypatch, tmp_path):
    """INFRA-493 (C4): el SOUL sembrado dice solo lo que el chart permite. Es de solo lectura (el
    bloque lo dice), no promete compras ni escritura, y no afirma que los demás agentes le escriban
    con `delegar` mientras ninguna fila de `empresa.permisos` la nombre (la fija security).
    Los `servers` siguen sin escritura: lo fija test_servers_solo_lectura_sin_ningun_plano_de_escritura."""
    home = seed(str(tmp_path / "h"))
    soul = (home / "profiles" / PERFIL / "SOUL.md").read_text()
    propio = VALUES["souls"][PERFIL] + VALUES["herencia"]["bloques"]["tono-skirmshop"]
    assert "solo lectura" in propio and "no compras, no pagas" in propio
    assert "tono-skirmshop" not in soul  # el nombre del bloque no se cuela en el texto
    # el bloque propio no copia ni el oficio ni el org
    for otro in ("oficio-secretaria", "org"):
        cab = VALUES["herencia"]["bloques"][otro].splitlines()[0].strip()
        assert cab not in propio
    nadie_le_delega = all(PERFIL not in fila for p, fila in VALUES["empresa"]["permisos"].items()
                          if p != PERFIL)
    if nadie_le_delega:
        assert "te escribe Dani y los demás agentes" not in propio
        assert "aún no pueden encargarte nada con `delegar`" in VALUES["souls"][PERFIL]
    assert "social" not in _spec()["servers"] and PERFIL not in VALUES["pagos"]["perfiles"]


def test_acotacion_es_lo_ultimo_que_lee_el_modelo(tmp_path):
    """INFRA-493 (architect, #528): el oficio ordena cosas que este perfil no puede (Acciones ACC,
    confirmar_pago, social, calendar_create_event, Reminders, brain `personal`); el bloque propio las
    acota y va el ÚLTIMO heredado, para que sea lo último del SOUL sembrado."""
    assert VALUES["herencia"]["hereda"][PERFIL][-1] == "tono-skirmshop"
    soul = (seed(str(tmp_path / "h")) / "profiles" / PERFIL / "SOUL.md").read_text()
    acota = "Del oficio de secretaria, que lees después, NO te aplica"
    assert acota in soul
    assert soul.rindex(acota) > soul.rindex("## El oficio de secretaria")
    assert soul.rindex(acota) > soul.rindex("## Recibir encargos")
    cola = soul[soul.rindex(acota):]
    for cosa in ("ACC", "confirmar_pago", "calendar_create_event", "social", "Reminders", "`skirmshop`"):
        assert cosa in cola, cosa
    # el digest se conserva solo porque el perfil tiene el toolset cronjob
    assert "cronjob" in VALUES["webhook"]["routes"][PERFIL]["toolsets"]
    assert "el digest (tu cronjob)" in cola


def test_el_soul_de_la_tienda_lleva_el_procedimiento_de_datos_antes_de_redactar(tmp_path):
    """DGX-788 (C2): el bloque `borrador-skirmshop` está en el SOUL sembrado de esta secretaria y de ninguna otra, entre
    `correo-borrador` (que afina) y `tono-skirmshop` (que sigue siendo lo último), y fija el procedimiento (a-f) con los nombres
    REALES de las herramientas que el turno ve: cada una está en `servers` del perfil, que a su vez es de solo lectura."""
    home = seed(str(tmp_path / "h"))
    cabecera = "## Borradores de la tienda: datos antes de redactar"
    soul = (home / "profiles" / PERFIL / "SOUL.md").read_text()
    assert soul.count(cabecera) == 1
    assert (soul.index("## Correo: avisar y preparar borradores") < soul.index(cabecera)
            < soul.index("## Tono y límites de la secretaria de la tienda"))
    for otra in SECRETARIAS[:-1]:
        assert cabecera not in (home / "profiles" / otra / "SOUL.md").read_text(), otra
    bloque = VALUES["herencia"]["bloques"]["borrador-skirmshop"]
    assert "borrador-skirmshop" not in soul  # el nombre del bloque no se cuela en el texto
    # (a) pedido y cliente con Shopify · (b) datos solo al cliente del pedido · (c) consultar · (d) datos + UN paso
    # (e) prohibido prometer sin comprobar · (f) escribir = tarea para Dani, no la hace ella
    for pieza in ("ANTES", "antes de `gmail_create_draft`", "`get-orders`", "`get-order`", "`get-customers`", "`de:`",
                  "solo si el email de `de:` es el del cliente", "nº de pedido y email de compra", "`picqer_webshop_orders`",
                  "`picqer_shipments`", "`labels_shipment_status`", "`labels_rate_quote`", "`get-products`", "UN paso siguiente",
                  "Prohibido «estoy confirmando»", "cuál falta", "`tarea_ref`", "[Crear tarea]"):
        assert pieza.lower() in bloque.lower(), pieza
    servers = _spec()["servers"]
    vistas = {t for tools in servers.values() for t in tools}
    nombres = set(re.findall(r"`([a-z]+[-_][a-z_-]+)`", bloque.split("\n", 1)[1])) - {"tarjeta_correo", "gmail_create_draft", "gmail_get_message", "tarea_ref"}
    assert nombres and nombres <= vistas, sorted(nombres - vistas)
