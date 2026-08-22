#!/usr/bin/env python3
"""Revisa un diff con un LLM servido por LiteLLM y publica el veredicto.

Pensado para correr en los runners ARC del cluster (`arc-k8s`), cuya imagen
trae python3 pero NO trae pip, ni xz, ni bunx, ni gh — y esas ausencias fallan
MUDAS, sin una linea de error. De ahi que aqui solo haya libreria estandar y
que GitHub se hable por REST con urllib, nunca con `gh`.

Todo entra por VARIABLES DE ENTORNO. El titulo del PR, el nombre de rama y el
diff son texto de TERCEROS: una interpolacion `${{ }}` dentro de un `run` seria
inyeccion de shell directa. Por lo mismo el workflow que llama se dispara con
`pull_request` y NUNCA con `pull_request_target`.

Dos modos, segun REVIEW_PR_NUMBER:
  - con numero de PR  -> comentario en el PR (se ACTUALIZA el anterior del bot).
  - sin numero        -> comentario de commit sobre REVIEW_SHA (modo validacion).
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

# El propio runner publica GITHUB_API_URL; usarlo en vez de una constante
# es lo que hace que esto funcione tambien contra GitHub Enterprise.
GITHUB_API = os.environ.get('GITHUB_API_URL') or 'https://api.github.com'

# Marca invisible para reencontrar el comentario propio y ACTUALIZARLO en vez
# de acumular uno por push. Si se cambia, los comentarios viejos quedan
# huerfanos y el bot empieza a duplicar.
MARCA = '<!-- llm-review-bot:v1 -->'

# GitHub corta el cuerpo de un comentario en 65536 caracteres.
LIMITE_COMENTARIO = 60000

# El `resumen` acaba en un aviso de Telegram, que corta en 4096.
LIMITE_RESUMEN = 500

ORDEN_SEVERIDAD = {'alta': 0, 'media': 1, 'baja': 2}

SISTEMA = (
    'Eres un revisor de codigo senior. Revisas diffs unificados de git y '
    'devuelves SOLO un objeto JSON valido, sin texto alrededor y sin vallas '
    'de codigo.'
)

PLANTILLA = """Revisa el siguiente diff y señala problemas CONCRETOS y ACCIONABLES:
bugs, condiciones de carrera, inyección, secretos filtrados, errores sin manejar,
rupturas de contrato o de API, y riesgos de seguridad. No comentes estilo,
formato ni preferencias personales.

Responde en español y SOLO con este JSON:
{{"resumen": "<una o dos frases>",
  "hallazgos": [{{"file": "ruta/al/fichero", "line": 42,
                 "severity": "alta|media|baja",
                 "summary": "<qué pasa y qué hacer>"}}]}}

Si no hay nada reseñable, devuelve "hallazgos": [].

Repositorio: {repo}

Diff:
{diff}
"""


def env(nombre, defecto=''):
    return (os.environ.get(nombre) or defecto).strip()


def entero(nombre, defecto):
    try:
        return int(env(nombre) or defecto)
    except ValueError:
        print(f'::warning::{nombre} no es un entero; se usa {defecto}')
        return defecto


def sin_token(texto, *tokens):
    """Los mensajes de error de urllib incluyen la URL y a veces la cabecera.
    Dentro de Actions el secreto va enmascarado; ejecutado a mano, no.
    Mismo criterio que `sin_token` en notify_telegram.py."""
    for token in tokens:
        if token:
            texto = texto.replace(token, '***')
    return texto


def salida(nombre, valor):
    """Formato con delimitador: `resumen` puede traer saltos de linea del
    modelo y un `nombre=valor` suelto romperia el fichero de salidas."""
    destino = os.environ.get('GITHUB_OUTPUT')
    if not destino:
        print(f'[salida] {nombre}={valor}')
        return
    delim = f'__fin_{nombre}_{os.urandom(8).hex()}__'
    with open(destino, 'a', encoding='utf-8') as fh:
        fh.write(f'{nombre}<<{delim}\n{valor}\n{delim}\n')


def resumen_paso(cuerpo):
    """El review va SIEMPRE al resumen del job, publicado o no. Si GitHub
    rechaza el comentario (token de solo lectura, PR de un fork), el trabajo
    del modelo no se pierde."""
    destino = os.environ.get('GITHUB_STEP_SUMMARY')
    if not destino:
        return
    with open(destino, 'a', encoding='utf-8') as fh:
        fh.write(cuerpo + '\n')


# --------------------------------------------------------------------------
# Diff
# --------------------------------------------------------------------------

def trocear_por_ficheros(diff):
    """Parte un diff unificado en bloques, uno por fichero. Se corta por
    `diff --git`, que es la unica frontera fiable: dentro de un bloque puede
    haber lineas que empiezan por `---`, `+++` o `@@` como CONTENIDO."""
    if not diff:
        return []
    partes = re.split(r'(?m)^(?=diff --git )', diff)
    return [p for p in partes if p.strip()]


def nombre_fichero(bloque):
    m = re.match(r'diff --git a/(.+?) b/(.+?)$', bloque.split('\n', 1)[0])
    return m.group(2) if m else '(desconocido)'


def recortar(diff, max_bytes):
    """Tope DURO por ficheros enteros, nunca a mitad de linea.

    Motivo: el contexto del modelo es finito, el servidor corre con
    `--max-num-seqs 5` (un diff enorme monopoliza la GPU compartida) y el aviso
    de Telegram corta en 4096. Un diff cortado a mitad de linea, ademas, hace
    que el modelo invente el resto del hunk.

    Devuelve (diff_recortado, ficheros_fuera)."""
    if len(diff.encode('utf-8')) <= max_bytes:
        return diff, []
    dentro, fuera, usado = [], [], 0
    for bloque in trocear_por_ficheros(diff):
        peso = len(bloque.encode('utf-8'))
        if usado + peso <= max_bytes:
            dentro.append(bloque)
            usado += peso
        else:
            fuera.append((nombre_fichero(bloque), peso))
    return ''.join(dentro), fuera


# --------------------------------------------------------------------------
# LiteLLM
# --------------------------------------------------------------------------

def url_chat(base):
    """Acepta la raiz de LiteLLM o la ruta completa; DevOps puede configurar
    cualquiera de las dos sin que esto reviente."""
    b = base.rstrip('/')
    if b.endswith('/chat/completions'):
        return b
    if b.endswith('/v1'):
        return b + '/chat/completions'
    return b + '/v1/chat/completions'


def pedir(url, key, modelo, prompt, timeout):
    """Devuelve (estado, dato) con estado in {ok, degradado, config}.

    DEGRADADO ES VERDE, y esa es la regla que manda aqui: los Sparks sirven UN
    perfil de computo a la vez y son excluyentes. Con el arbitro en `creative`,
    DeepSeek NO tiene endpoints y LiteLLM responde 500/503 o la conexion ni se
    abre. 113 checks en rojo porque el arbitro cambio de perfil es peor que no
    tener bot: el bot se calla y el PR sigue.

    Un 401/403, en cambio, SI es rojo: la key esta mal o el equipo no tiene el
    alias en su allowlist. Eso es configuracion rota, no indisponibilidad, y
    callarlo dejaria el bot muerto sin que nadie se entere."""
    cuerpo = json.dumps({
        'model': modelo,
        'messages': [
            {'role': 'system', 'content': SISTEMA},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0.1,
        'max_tokens': 1500,
        'stream': False,
    }).encode('utf-8')
    req = urllib.request.Request(url, data=cuerpo, headers={
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {key}',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 'ok', json.loads(resp.read().decode('utf-8', 'replace'))
    except urllib.error.HTTPError as e:
        detalle = sin_token(e.read().decode('utf-8', 'replace')[:400], key)
        if e.code in (408, 429) or e.code >= 500:
            return 'degradado', f'HTTP {e.code}: {detalle}'
        return 'config', f'HTTP {e.code}: {detalle}'
    except Exception as e:  # noqa: BLE001  timeout, DNS, conexion rechazada
        # Sin endpoints el Service ni siquiera acepta la conexion: eso es
        # indisponibilidad, no configuracion rota.
        return 'degradado', sin_token(str(e), key)


def consultar(url, key, modelo, prompt, timeout):
    """SIN reintentos, y 429 y 5xx tratados IGUAL. Medido en el cluster: el
    alias no tiene `fallbacks` en `router_settings`, asi que sin endpoints
    LiteLLM da 500 y despues un 429 que se INVENTA el cooldown del router
    durante 120 s. Reintentar dentro de esa ventana solo quema runner para
    acabar igual de degradado, y el scale set `arc-k8s` tiene maxRunners=3
    para toda la organizacion."""
    estado, dato = pedir(url, key, modelo, prompt, timeout)
    if estado == 'degradado':
        print(f'::warning::LiteLLM no disponible ({dato}); review omitida')
    return estado, dato


def contenido(respuesta):
    """Saca el texto de la respuesta estilo OpenAI y distingue el caso en que
    el modelo razona hasta agotar `max_tokens` y devuelve `content` VACIO:
    eso no es un review, es una no-respuesta, y se trata como degradado."""
    try:
        eleccion = respuesta['choices'][0]
    except (KeyError, IndexError, TypeError):
        return None, 'respuesta sin `choices`'
    mensaje = eleccion.get('message') or {}
    texto = (mensaje.get('content') or '').strip()
    if not texto:
        return None, (f'contenido vacio (finish_reason='
                      f'{eleccion.get("finish_reason")!r})')
    return texto, None


# --------------------------------------------------------------------------
# Parseo defensivo
# --------------------------------------------------------------------------

def extraer_json(texto):
    """El modelo promete JSON; a veces entrega JSON dentro de una valla, o con
    un parrafo delante. Se intenta en ese orden y, si nada cuela, se devuelve
    None para publicar el texto CRUDO: un review util mal envuelto vale mas
    que una excepcion."""
    for candidato in (texto,):
        try:
            return json.loads(candidato)
        except ValueError:
            pass
    valla = re.search(r'```(?:json)?\s*(.+?)```', texto, re.S)
    if valla:
        try:
            return json.loads(valla.group(1))
        except ValueError:
            pass
    ini, fin = texto.find('{'), texto.rfind('}')
    if 0 <= ini < fin:
        try:
            return json.loads(texto[ini:fin + 1])
        except ValueError:
            pass
    return None


def normalizar(dato):
    hallazgos = []
    bruto = dato.get('hallazgos')
    if isinstance(bruto, list):
        for h in bruto:
            if not isinstance(h, dict):
                # Una lista de cadenas tambien es una respuesta razonable.
                hallazgos.append({'file': '', 'line': '', 'severity': 'media',
                                  'summary': str(h)})
                continue
            sev = str(h.get('severity') or 'media').strip().lower()
            hallazgos.append({
                'file': str(h.get('file') or h.get('fichero') or ''),
                'line': str(h.get('line') or h.get('linea') or ''),
                'severity': sev if sev in ORDEN_SEVERIDAD else 'media',
                'summary': str(h.get('summary') or h.get('resumen') or '').strip(),
            })
    hallazgos = [h for h in hallazgos if h['summary']]
    hallazgos.sort(key=lambda h: ORDEN_SEVERIDAD[h['severity']])
    return hallazgos, str(dato.get('resumen') or '').strip()


# --------------------------------------------------------------------------
# Comentario
# --------------------------------------------------------------------------

def componer(estado, hallazgos, resumen, crudo, fuera, modelo, ficheros):
    lineas = [MARCA, '## Review automatica']
    if estado == 'omitido':
        lineas += ['', f'⏭️ Modelo no disponible, review omitida. {resumen}', '',
                   '_El perfil de computo de los Sparks se conmuta entre '
                   '`llm-tp` y `creative`; en `creative` el modelo no tiene '
                   'endpoints. El check queda en verde a proposito._']
    elif crudo is not None:
        lineas += ['', 'El modelo no devolvio JSON valido. Texto tal cual:', '',
                   '```', crudo[:8000], '```']
    elif not hallazgos:
        lineas += ['', f'✅ Sin hallazgos sobre {ficheros} fichero(s).']
        if resumen:
            lineas += ['', resumen]
    else:
        lineas += ['', f'Se revisaron {ficheros} fichero(s). '
                       f'{len(hallazgos)} hallazgo(s):', '']
        if resumen:
            lineas += [resumen, '']
        for h in hallazgos:
            donde = h['file'] + (f":{h['line']}" if h['line'] else '')
            lineas.append(f"- **[{h['severity']}]** `{donde or 'general'}` — "
                          f"{h['summary']}")
    if fuera:
        lineas += ['', '<details><summary>Diff recortado: '
                       f'{len(fuera)} fichero(s) fuera del tope</summary>', '']
        lineas += [f'- `{n}` ({b} B)' for n, b in fuera]
        lineas += ['', '</details>']
    lineas += ['', f'<sub>modelo `{modelo}` · revision no bloqueante</sub>']
    cuerpo = '\n'.join(lineas)
    if len(cuerpo) > LIMITE_COMENTARIO:
        cuerpo = cuerpo[:LIMITE_COMENTARIO] + '\n\n… (comentario truncado)'
    return cuerpo


# --------------------------------------------------------------------------
# GitHub REST (sin `gh`: la imagen de arc-k8s no lo trae y falla mudo)
# --------------------------------------------------------------------------

def github(token, metodo, ruta, datos=None):
    url = ruta if ruta.startswith('http') else GITHUB_API + ruta
    cuerpo = json.dumps(datos).encode('utf-8') if datos is not None else None
    req = urllib.request.Request(url, data=cuerpo, method=metodo, headers={
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'Content-Type': 'application/json',
        'User-Agent': 'llm-review-bot',
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode('utf-8', 'replace') or 'null')


def publicar(token, repo, pr, sha, cuerpo):
    """Un solo comentario por PR: si ya hay uno con la MARCA, se actualiza.

    Un fallo aqui NO tumba el job, ni siquiera un 403: un PR desde un fork trae
    token de SOLO LECTURA (precio correcto de no usar `pull_request_target`) y
    un repo con permisos por defecto restringidos tampoco puede comentar. El
    review ya esta en el resumen del job, asi que se avisa y se sigue."""
    if pr:
        listado = f'/repos/{repo}/issues/{pr}/comments?per_page=100'
        crear = f'/repos/{repo}/issues/{pr}/comments'
        editar = f'/repos/{repo}/issues/comments/{{id}}'
    else:
        listado = f'/repos/{repo}/commits/{sha}/comments?per_page=100'
        crear = f'/repos/{repo}/commits/{sha}/comments'
        editar = f'/repos/{repo}/comments/{{id}}'
    try:
        previos = github(token, 'GET', listado) or []
        anterior = next((c for c in previos if MARCA in (c.get('body') or '')),
                        None)
        if anterior:
            github(token, 'PATCH', editar.format(id=anterior['id']),
                   {'body': cuerpo})
            print(f'comentario {anterior["id"]} actualizado')
        else:
            nuevo = github(token, 'POST', crear, {'body': cuerpo})
            print(f'comentario {nuevo.get("id")} publicado')
        return True
    except urllib.error.HTTPError as e:
        detalle = e.read().decode('utf-8', 'replace')[:300]
        print(f'::warning::GitHub rechazo el comentario (HTTP {e.code}): '
              f'{detalle}; el review queda en el resumen del job')
    except Exception as e:  # noqa: BLE001
        print(f'::warning::no se pudo publicar el comentario: {e}; '
              f'el review queda en el resumen del job')
    return False


# --------------------------------------------------------------------------

def terminar(veredicto, resumen, n, cuerpo=None, codigo=0):
    salida('veredicto', veredicto)
    salida('resumen', resumen[:LIMITE_RESUMEN].replace('\n', ' ').strip())
    salida('n_hallazgos', str(n))
    if cuerpo:
        resumen_paso(cuerpo)
    print(f'veredicto={veredicto} n_hallazgos={n}')
    return codigo


def main():
    url_base = env('REVIEW_LITELLM_URL')
    key = env('REVIEW_LITELLM_KEY')
    modelo = env('REVIEW_MODEL')
    token = env('REVIEW_GITHUB_TOKEN')
    repo = env('REVIEW_REPO')
    pr = env('REVIEW_PR_NUMBER')
    sha = env('REVIEW_SHA')
    max_bytes = entero('REVIEW_MAX_DIFF_BYTES', 120000)
    # 120 s, muy por debajo de los 600 que hereda el proxy: un job
    # colgado ocupa un tercio del CI de la organizacion (maxRunners=3)
    # hasta las 6 h de timeout por defecto de GitHub.
    timeout = entero('REVIEW_TIMEOUT_SECONDS', 120)

    fichero = env('REVIEW_DIFF_FILE')
    diff = os.environ.get('REVIEW_DIFF') or ''
    if fichero:
        try:
            with open(fichero, encoding='utf-8', errors='replace') as fh:
                diff = fh.read()
        except OSError as e:
            print(f'::error::no se pudo leer el diff en {fichero}: {e}')
            return terminar('omitido', 'no se pudo leer el diff', 0, codigo=1)

    if not url_base or not modelo or not repo:
        print('::error::faltan litellm_url, model o repo')
        return terminar('omitido', 'configuracion incompleta', 0, codigo=1)
    if not pr and not sha:
        print('::error::hace falta pr_number o sha')
        return terminar('omitido', 'configuracion incompleta', 0, codigo=1)

    if not diff.strip():
        cuerpo = componer('ok', [], 'El diff esta vacio.', None, [], modelo, 0)
        if token:
            publicar(token, repo, pr, sha, cuerpo)
        return terminar('ok', 'sin cambios que revisar', 0, cuerpo)

    if not key:
        # Falta el secreto, que NO es lo mismo que una key rechazada: durante
        # el despliegue por los 113 repos habra repos activos antes de que el
        # secreto de organizacion llegue. Verde y aviso, no rojo.
        print('::warning::sin LITELLM_CI_KEY; review omitida')
        cuerpo = componer('omitido', [], 'Falta el secreto LITELLM_CI_KEY.',
                          None, [], modelo, 0)
        if token:
            publicar(token, repo, pr, sha, cuerpo)
        return terminar('omitido', 'falta LITELLM_CI_KEY', 0, cuerpo)

    recortado, fuera = recortar(diff, max_bytes)
    ficheros = len(trocear_por_ficheros(recortado))
    if fuera:
        print(f'::warning::diff recortado: {len(fuera)} fichero(s) fuera del '
              f'tope de {max_bytes} B')

    estado, dato = consultar(url_chat(url_base), key, modelo,
                             PLANTILLA.format(repo=repo, diff=recortado),
                             timeout)
    if estado == 'config':
        # Rojo a proposito: key invalida o alias fuera del allowlist del equipo.
        print(f'::error::LiteLLM rechazo la peticion: {dato}')
        return terminar('omitido', f'LiteLLM rechazo la peticion: {dato}', 0,
                        codigo=1)
    if estado == 'degradado':
        cuerpo = componer('omitido', [], str(dato), None, fuera, modelo,
                          ficheros)
        if token:
            publicar(token, repo, pr, sha, cuerpo)
        return terminar('omitido', f'modelo no disponible: {dato}', 0, cuerpo)

    texto, fallo = contenido(dato)
    if texto is None:
        print(f'::warning::respuesta inutil del modelo: {fallo}')
        cuerpo = componer('omitido', [], str(fallo), None, fuera, modelo,
                          ficheros)
        if token:
            publicar(token, repo, pr, sha, cuerpo)
        return terminar('omitido', f'respuesta inutil: {fallo}', 0, cuerpo)

    dato_json = extraer_json(texto)
    if dato_json is None or not isinstance(dato_json, dict):
        cuerpo = componer('hallazgos', [], '', texto, fuera, modelo, ficheros)
        if token:
            publicar(token, repo, pr, sha, cuerpo)
        return terminar('hallazgos', 'el modelo no devolvio JSON valido', 0,
                        cuerpo)

    hallazgos, resumen = normalizar(dato_json)
    veredicto = 'hallazgos' if hallazgos else 'ok'
    cuerpo = componer(veredicto, hallazgos, resumen, None, fuera, modelo,
                      ficheros)
    if token:
        publicar(token, repo, pr, sha, cuerpo)
    else:
        print('::warning::sin github_token; el review solo va al resumen')
    corto = resumen or (f'{len(hallazgos)} hallazgo(s)' if hallazgos
                        else 'sin hallazgos')
    return terminar(veredicto, corto, len(hallazgos), cuerpo)


if __name__ == '__main__':
    sys.exit(main())
