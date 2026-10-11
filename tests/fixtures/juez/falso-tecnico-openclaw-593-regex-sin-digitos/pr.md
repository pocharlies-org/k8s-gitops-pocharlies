DGX-788: el borrador de la tienda consulta pedido, envío y tarifas antes de redactar

Dani 10-10: «el borrador es súper genérico». El borrador de prueba de DGX-765 contestó «estoy confirmando con el almacén» porque el turno del aviso (`gmail-skirmshop`, `toolsets: brain, workspace`) no veía Shopify, Picqer ni las tarifas de etiquetas.

## Alcance de esta PR
- C1: la ruta `gmail-skirmshop` lleva exactamente `brain, workspace, shopify, picqer, skirmshop-plugins`; las otras `gmail-*` no cambian; test con igualdad exacta por ruta
- C2: bloque SOUL `borrador-skirmshop`, propio de `secretaria-skirmshop`, con el procedimiento (a-f) y test de presencia y techo de palabras
- C3: suite del repo en verde

## Qué cambia
- `helm/hermes/values.yaml`: `webhook.routes.gmail-skirmshop.toolsets` gana `shopify`, `picqer`, `skirmshop-plugins`; el comentario de las condiciones de INFRA-582 dice por qué; bloque `herencia.bloques.borrador-skirmshop` (201 palabras, techo 209) añadido a `herencia.hereda.secretaria-skirmshop` entre `correo-borrador` y `tono-skirmshop` (que sigue siendo lo último que lee).
- Herramientas que gana el turno (las acota `profiles.secretaria-skirmshop.servers`, todas de solo lectura): `shopify` 10 (`get-order`, `get-orders`, `get-customers`, `get-products`, `get-products-by-ids`, `get-products-by-collection`, `get-variants-by-ids`, `get-collections`, `get-shop`, `get-shop-details`), `picqer` 6 (`picqer_webshop_orders`, `picqer_shipments`, `picqer_stats`, `picqer_reference_data`, `picqer_warehouses`, `picqer_users`), `skirmshop-plugins` 5 (`labels_rate_quote`, `labels_shipment_status`, `labels_correos_fuel_surcharge`, `skirmshop_plugins_list`, `skirmshop_plugins_describe`). Sin terminal, file, social, cronjob ni compuestos `hermes-*`; enviar sigue siendo de los dos toques del aprobador.
- `tests/`: igualdad exacta por ruta (`test_hermes_webhook_gmail.py`, falla sin el cambio), bloque en el SOUL sembrado y sus nombres de herramienta contra `servers` (`test_hermes_secretaria_skirmshop_perfil.py`), techo (`test_hermes_soul_tamano.py` + fixture).
- `CONTRACTS.yaml`: nota DGX-788 en `http.webhook.hermes_gmail_notify`; superficie sin cambios (nombre, ruta, secreto, `rate_limit`, `deliver`, cuerpo), el adapter no lee `toolsets`.

## Verificación
- `helm template`: `gmail-skirmshop` → `[brain, workspace, shopify, picqer, skirmshop-plugins]`; las otras cuatro, `[brain, workspace]`.
- `bash scripts/validate.sh`: ver el check de la PR.
- Riesgo alto (un aviso de correo externo gana lectura de datos de clientes): pide veredicto de security; el bloque solo da datos si el remitente es el cliente del pedido.
- Despliegue: solo values y SOUL, recarga en caliente; las rutas de webhook las lee el seed, que decide si hace falta el reinicio ordenado.

## Evidencia C3
- Comando: `bash scripts/validate.sh` (x86, worktree de la rama `dgx-788-borrador-con-datos`, 2026-10-10T01:12:55Z)
- Head de código validado: `c4e6046a` (rama al día con `origin/deploy/prod` 87ae7dfc, DGX-760). El commit siguiente solo añade `.company/evidence/dgx-788-borrador-con-datos.md`
- Resultado: **PASS** (rc=0) — pytest del repo entero (incluye `tests/test_hermes_*.py`): 2316 passed, 176 warnings in 347.94s (0:05:47); regresión posterior a la promoción: 105 passed in 38.15s — VALIDATION OK
- Detalle en `.company/evidence/dgx-788-borrador-con-datos.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)

