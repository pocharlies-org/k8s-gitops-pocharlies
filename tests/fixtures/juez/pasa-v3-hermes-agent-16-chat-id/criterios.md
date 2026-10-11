# INFRA-776 · criterios del 00-spec.md

- [ ] GET /api/sessions?source=telegram del perfil studio devuelve chat_id y thread_id en cada fila (null si la sesión no tiene topic).
- [ ] Ningún campo existente cambia de nombre ni de forma: quien ya consume el listado sigue igual.
- [ ] Sin cambio de autenticación, de allowlist ni de hermes-config o hermes-inbox.json.
- [ ] Test automático del handler: fila con chat_id y thread_id; fila sin topic (null).
- [ ] PR contra la rama que lee el despliegue, sin checks en fallo (salvo el del juez, que es quien juzga estos criterios) y con los tests de Python ejecutados por qa sobre el head. El workflow `CI` (`ci.yaml`) del repo está `disabled_manually` y `tests.yml` solo admite `workflow_call`, así que no hay CI de tests que corra en la PR. Evidencia: `70-qa.md` (id 23875): `tests/gateway/test_session_api.py` 37 passed en el head, y el único fallo de los dos ficheros sospechosos (`tests/gateway/test_session_hygiene.py::test_hygiene_does_not_wait_ceiling_after_fence_cancel`) es idéntico en el head y en la base `2768af3`.
