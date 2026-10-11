# SC-2295 · criterios del 00-spec.md

- [ ] C1 Con `apagada`, `company-sesion lanzar` → NO, exit 3, «compañía apagada», sin sid ni unidad. Test en ci/test_company_sesion.py.
- [ ] C2 Con `apagada`, `company-sesion mensaje` a sesión PARADA no la reanuda (NO «compañía apagada»); a sesión VIVA, entregado. Test en ci/test_company_sesion.py.
- [ ] C3 Con `apagada`, bus / orquesta / `relanzar_duenos` no arrancan unidad `ses-*` ni `turno-*`; el encargo queda pendiente y arranca en el primer barrido tras encender. Tests en ci/test_company_encargos.py / ci/test_company_bus.py / ci/test_jira_epic_trigger.py.
- [ ] C4 Rol `secretaria` / ACC: sin cambios con la compañía apagada. Test.
- [ ] C5 Sin `apagada`, la suite existente en verde.
