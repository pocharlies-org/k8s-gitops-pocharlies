SC-2169: veredicto solo con la cuenta del rol

Durante el merge de SC-2152 el perfil sre-devops registró `aprobacion/qa` SUCCESS sobre el head 1764584c de k8s-openclaw-qwen36#574 sin ser qa. El motivo: la firma solo comparaba el rol de la sesión (`JIRA_ROL`) con el `--rol` cuando `COMPANY_SESION=1`, y un perfil de Hermes no lleva esa marca — firmaba con cuenta prestada. Además, un `gh api POST .../statuses/<sha>` directo podía escribir el veredicto sin pasar por ningún control.

Cambios:
- La firma exige ahora que `--rol` coincida con `JIRA_ROL` siempre, dentro y fuera de una sesión de la compañía. Sin `JIRA_ROL` y fuera de sesión sigue firmando el subagente en vivo (SC-2222), cuya identidad juzga el guard de company-roles por `agent_type`.
- El envoltorio de `gh` bloquea `gh api .../statuses/<sha>` que mencione `aprobacion/`: la firma pasa por la herramienta de aprobación o no pasa.
- Contrato nuevo declarado: `cli.company-aprobar.aprobar` (registro + marcador), y tests de la regla en ambas rutas.

No hay credenciales implicadas: la firma salía con el token compartido de GitHub (`pocharlies`), que sigue siendo el único; la identidad del rol se aplica en la ruta de firma, no en el token.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

