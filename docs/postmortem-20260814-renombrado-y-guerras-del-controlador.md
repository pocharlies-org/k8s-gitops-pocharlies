# Post-mortem 13/14-08-2026 — el renombrado por roles y las guerras del controlador

Autor: Claude (sesión de ~/k8s), a petición de Dani. Este documento es sobre
**mis** errores durante la operación, no sobre los del sistema. Los del sistema
están en el registro de commits; los míos son los que hay que recordar para que
el siguiente agente no los repita.

## Qué se hizo (contexto en una línea)

El ns `llm` pasó de 16 objetos nombrados por nodo (`-rtx/-dgx1/-dgx2/-x86`) a
**cero**, con la doctrina "el Deployment dice QUÉ se despliega, jamás el nodo",
en ~24 h con dos sesiones operando el mismo clúster. Validación final:
12 PASS / 0 FAIL. Tag: `nombres-por-rol-20260814` en los 6 repos.

## Mis dramas, por orden de aparición

### 1. Empecé renombrando sin preguntar qué eran las cosas
Propuse `-gb10` como nombre nuevo — hardware otra vez, el mismo error que estaba
arreglando. Y creé `stt-turbo-x86`: un clon por nodo, el anti-patrón exacto, la
misma noche que el dueño formuló la regla. **Causa raíz: imité la convención
existente sin auditarla.** La regla que lo arregla: antes de nombrar, diff de
artefactos (imagen/cuantización/device) — el nombre sale de ahí, no del nodo.

### 2. Re-pineé el dashboard en mitad de un lease del árbitro
Mi rollout del backend aterrizó mientras ComfyUI tenía el lease y DeepSeek
estaba desalojado (comportamiento normal). El watcher recién nacido vio "drift"
y resucitó a DeepSeek contra el job en curso. La otra sesión tuvo que mitigar en
vivo (flag→0). **Causa raíz: el gate de `evicted[]` existía para borrados y no
lo apliqué a rollouts del controlador.** Ahora es regla: mirar
`cm/gpu-arbiter-state` antes de CUALQUIER re-pin del dashboard.

### 3. Dos POST al mismo endpoint = dos transiciones en guerra
Para recuperar DeepSeek usé la palanca de diseño (`POST /api/compute/mode`)…
dos veces. Traefik balanceó cada POST a un pod distinto, `_launch` ejecuta EN EL
PROCESO QUE ATIENDE, y las dos transiciones se mataron los pods mutuamente
(`_stop_profile` de una contra el arranque de la otra) durante ~40 min.
**Causa raíz: no sabía que el endpoint no estaba gateado por el flag.** Fix
permanente: request_mode devuelve 503 sin flag; supersesión por transition_id.

### 4. El pin huérfano
Empujé el re-pin de gitops ANTES de confirmar el push de la rama: la rama avanzó
entre mi commit y mi push, el push rebotó, y el pin quedó apuntando a un SHA que
no existía en ningún remoto. Argo no resuelve SHAs sin rama. **Regla: el pin se
escribe DESPUÉS de ver el push confirmado, nunca en el mismo aliento.**

### 5. El apiVersion que congeló la app entera
Al partir un Service en canónico+deprecado me comí un `apiVersion: v1`.
`kubectl kustomize` renderiza igual; ArgoCD no: la Application `ai` ENTERA quedó
en ComparisonError (`groupVersion shouldn't be empty`), sin reconciliar nada.
**Regla: la validación post-render comprueba apiVersion/kind en TODOS los docs,
no solo el diff.** (Desde entonces, en cada render de la noche.)

### 6. Los bots eran controladores y nadie lo sabía
No es error mío de origen (default `"1"` + envs sin setear), pero MI lockstep
los reinició y su reconcile relanzó la transición persistida: fp16, reranker-cpu
y DeepSeek a 0 a las 02:04, en paralelo al controlador legítimo. Tres
controladores, una guerra. **Fix permanente: default `"0"`, bots a `"0"`
explícito, y las vacunas de supersesión.**

### 7. Mi validador también mintió
Dos FAIL de mi propio script eran bugs del script (pod hardcodeado que rotó,
filtro de RBAC mal escrito), no del sistema. **La regla del harness aplica
también al validador: si un check falla, lo primero es dudar del check.**

## Lo que funcionó y hay que conservar

- **Apilar sobre la rama del pin vivo** en vez de abrir ramas paralelas: 5
  carreras de pin con la otra sesión, cero trabajo perdido al final.
- **Expand → dashboard lockstep → contract**, con render diffeado contra el pin
  antes de cada push y ROLLBACK de una línea en cada pin.
- **El approval bundle de OpenClaw**: burocrático a las 3 AM, y exactamente por
  eso el único cambio que salió a la primera y sin sustos.
- **La disciplina RHO**: la máquina verifica, salida pegada. Los dos incidentes
  se diagnosticaron con eventos y estado, no con hipótesis.

## Deuda que queda (dueños claros)

1. `comfyui-rtx`: último nombre con hardware (ns comfyui). Toca claves del
   árbitro, lanes y leases persistidos — con plan propio, no de madrugada.
2. bge multi-arch: bloqueado por `FROM vllm-mxfp4:latest` (imagen local, en
   ningún registry). El workflow ya existe; falta publicar la base.
3. opencode→litellm roto en el x86 (err_d845c33d): sin él no hay ejecutor RHO.
4. `dgx2_model_mode` + legacy de `routes_cluster`: plano muerto tras la fusión
   del 27B; degrada solo, pero es código a retirar.
