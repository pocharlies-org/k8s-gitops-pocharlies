#!/usr/bin/env python3
"""Publica un aviso en un topic del grupo de Telegram de la organizacion.

Implementacion UNICA para las pipelines de pocharlies-org. Sale de fundir dos
que hacian lo mismo distinto:

  - release-bot-pocharlies (openchamber, shield, loki, opencode-claude): mapa
    de topics por nombre, icono por estado, y FALLA el paso si Telegram
    rechaza el mensaje — el silencio no puede confundirse con exito.
  - k8s-openclaw-qwen36-pocharlies: seis `curl` sueltos que se tragaban el
    fallo; de ahi vienen el recorte a 4096 y el texto plano por defecto
    (los asuntos de commit traen backticks y guiones bajos que rompen
    Markdown y devuelven 400).

Todo entra por VARIABLES DE ENTORNO, nunca por argv ni por interpolacion
`${{ }}` en el shell: el texto lo componen asuntos de commit de terceros.

Solo libreria estandar: la imagen de arc-k8s trae python3 pero NO pip, y ahi
las ausencias fallan MUDAS.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

API = 'https://api.telegram.org/bot{token}/{metodo}'

# Estados que sabe publicar, con su icono. El texto lo compone quien llama.
# Los nueve primeros vienen del release-bot y su icono NO se toca: cambiarlo
# cambiaria el aspecto de los avisos de openchamber que ya funcionan.
ICONOS = {
    'detectada':   '🔔',
    'rebase':      '🧩',
    'audit_ok':    '✅',
    'audit_fail':  '❌',
    'canary':      '🚦',
    'e2e_ok':      '🧪',
    'promovido':   '🚀',
    'rollback':    '↩️',
    'sin_cambios': '💤',
    # Anadidos al unificar con la pipeline de openclaw.
    'lanzado':     '🚀',
    'build':       '🔨',
    'ok':          '✅',
    'fallo':       '❌',
    'notas':       '🔖',
    'esperando':   '⏸️',
    # El parte diario: es una lista, no un suceso.
    'parte':       '📋',
}

# Telegram corta en 4096; se deja margen para el icono y el aviso de recorte.
LIMITE = 3900


def env(nombre, defecto=''):
    return (os.environ.get(nombre) or defecto).strip()


def sin_token(texto, token):
    """La Bot API lleva el token EN EL PATH, y str(e) de urllib incluye la URL.
    Dentro de Actions va enmascarado; ejecutado a mano, no."""
    return texto.replace(token, '***') if token else texto


def llamar(token, metodo, datos):
    cuerpo = json.dumps(datos).encode()
    req = urllib.request.Request(
        API.format(token=token, metodo=metodo), data=cuerpo,
        headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detalle = sin_token(e.read().decode(errors='replace')[:300], token)
        return {'ok': False, 'error_code': e.code, 'description': detalle}
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'description': sin_token(str(e), token)}


def cargar_mapa(fichero, en_linea):
    """El mapa de topics es una PISTA committeada, no la verdad: la Bot API no
    expone "listar topics". Un JSON invalido es un error del que llama, no un
    motivo para publicar en el sitio equivocado."""
    if en_linea:
        return json.loads(en_linea)
    if fichero:
        with open(fichero, encoding='utf-8') as fh:
            return json.load(fh)
    return {}


def resolver_thread(token, chat, topic, mapa, fichero, crear):
    if topic in mapa:
        return str(mapa[topic]), None
    if not crear:
        # NO se crea por defecto: el fichero de mapa no se committea solo, asi
        # que crear aqui significa un topic NUEVO en cada ejecucion. Alta de
        # topic = commit en el mapa, a mano y una vez.
        return None, f'el topic "{topic}" no esta en el mapa'
    r = llamar(token, 'createForumTopic', {'chat_id': chat, 'name': topic})
    if not r.get('ok'):
        return None, f'no se pudo crear el topic "{topic}": {r.get("description")}'
    tid = r['result']['message_thread_id']
    mapa[topic] = tid
    if fichero:
        with open(fichero, 'w', encoding='utf-8') as fh:
            json.dump(mapa, fh, indent=2, sort_keys=True)
            fh.write('\n')
        print(f'::notice::topic "{topic}" creado con id {tid}: hay que '
              f'committear {fichero} o el proximo run creara otro')
    return str(tid), None


# ---------------------------------------------------------------------------
# TITULARES: que significa cada estado, en castellano y sin jerga.
#
# Existe porque los avisos decian cosas como "auditoria success", "modo:
# notify_only" o "bump=failure": exacto para quien escribio el workflow e
# ilegible para quien lo lee en el movil un domingo. Cada aviso responde ahora
# a tres preguntas — QUE ha pasado, QUE significa, y SI hay que hacer algo.
#
# El detalle tecnico (commit, rama, resultados por job) no se pierde: baja al
# pie, detras de una linea separadora, y solo lo que sirve para copiar y pegar.
TITULARES = {
    'detectada':   ('{prog} tiene una versión nueva',
                    'Sus autores han publicado cambios.'),
    'rebase':      ('{prog}: nuestros cambios encajan con la versión nueva',
                    'Se han recolocado sobre ella sin conflictos.'),
    'audit_ok':    ('{prog}: la revisión ha salido bien',
                    'Compila, pasa los tests y conserva nuestras funciones.'),
    'audit_fail':  ('{prog}: la revisión ha fallado',
                    'No se despliega nada hasta que se mire.'),
    'canary':      ('{prog} está en pruebas',
                    'Desplegado en el entorno de pruebas, sin tocar producción.'),
    'e2e_ok':      ('{prog}: las pruebas automáticas pasan',
                    'Se ha comprobado que la aplicación funciona de verdad.'),
    'promovido':   ('{prog} ya está en producción',
                    'La versión nueva es la que se está usando.'),
    'rollback':    ('{prog}: se ha vuelto a la versión anterior',
                    'Algo falló al desplegar y se revirtió solo.'),
    'sin_cambios': ('{prog}: sin novedades', ''),
    'lanzado':     ('{prog}: empieza el despliegue',
                    'Se está construyendo y luego se desplegará.'),
    'build':       ('{prog}: construyendo',
                    'Solo se construye; producción no se toca.'),
    'ok':          ('{prog}: todo correcto', ''),
    'fallo':       ('{prog}: algo ha fallado',
                    'Conviene mirarlo.'),
    'notas':       ('{prog}: cambios de esta versión', ''),
    'parte':       ('Parte de la mañana', ''),
    'esperando':   ('{prog} espera tu visto bueno',
                    'Está listo, pero no continúa sin que alguien lo apruebe.'),
}

# Que hacer. Vacio = no hay que hacer nada, y eso TAMBIEN se dice: el silencio
# deja al lector preguntandose si le tocaba algo.
ACCIONES = {
    'audit_fail': 'Hay que revisar el fallo antes de seguir.',
    'fallo':      'Hay que revisar el fallo antes de seguir.',
    'rollback':   'Producción está estable en la versión anterior. Conviene mirar qué pasó.',
    'esperando':  'Hace falta que alguien lo apruebe para que continúe.',
}


def componer(estado, texto, programa):
    """Titular + explicacion + que hacer + detalle tecnico al pie."""
    # El parte diario ya viene compuesto por quien lo genera: es una LISTA de
    # tickets, no un suceso. Trocearlo en narracion/pie separaria cada enlace
    # de su linea, y anadirle "no hay que hacer nada" contradiria justo lo que
    # el parte viene a decir.
    if estado == 'parte':
        return f'{ICONOS[estado]} {TITULARES[estado][0]}\n\n{texto.strip()}'
    if estado not in TITULARES:
        return f'{ICONOS.get(estado, "")} {texto}'.strip()

    titular, explicacion = TITULARES[estado]
    prog = programa or 'El proyecto'
    partes = [f'{ICONOS[estado]} {titular.format(prog=prog)}']

    cuerpo = [l for l in texto.strip().split('\n') if l.strip()]

    # El pie son las lineas que ya vienen como `clave: valor` o un enlace: eso
    # es detalle, no narracion.
    def es_detalle(l):
        low = l.strip().lower()
        return (low.startswith(('run:', 'rama:', 'commit:', 'sha:', 'upstream:',
                                'modo:', 'web:', 'mac:', 'canario', 'promocion',
                                'ref:', 'log:', 'branch:'))
                or low.startswith('http'))

    # Y se tira lo que el titular YA dice. Sin esto el aviso repite en medio la
    # linea vieja ("shield master@abc: auditoria success"), que es justo la
    # jerga que se venia a quitar. Tambien caen los SHA de 40 caracteres: nadie
    # lee eso, y los 12 primeros ya salen en el pie.
    RUIDO = ('auditoria success', 'auditoria failure', 'auditoria ', 'sin rama',
             'notify_only', 'audit_only', 'rebase limpio')

    def es_ruido(l):
        low = l.strip().lower()
        if any(r in low for r in RUIDO):
            return True
        # una linea que es solo el nombre del programa + un identificador
        if re.fullmatch(r'[\w.-]+ [0-9a-f]{7,40}', l.strip()):
            return True
        if re.fullmatch(r'[\w.-]+ [\w./@-]+ \([0-9a-f]{40}\)', l.strip()):
            return True
        return False

    # La narracion tambien se limpia de `clave=valor`: openclaw mandaba cosas
    # como "deploy_solicitado=false build=success bump=failure", que es un
    # volcado de variables, no una frase.
    JERGA = {
        'deploy_solicitado': 'despliegue pedido', 'build': 'construcción',
        'bump': 'subida de versión', 'true': 'sí', 'false': 'no',
        'success': 'bien', 'failure': 'ha fallado', 'skipped': 'no aplicaba',
    }

    def limpiar_jerga(l):
        if '=' not in l:
            return l
        # Se separan con coma: encadenar "a: b c: d" sin puntuacion se lee
        # peor que el original.
        def sust(m):
            k, v = m.group(1), m.group(2)
            return f'{JERGA.get(k, k)}: {JERGA.get(v, v)},'
        salida_l = re.sub(r'(\w+)=(\w+)', sust, l)
        return re.sub(r',\s*$', '', salida_l).replace(', ·', ' ·')

    narracion = [limpiar_jerga(l.strip()) for l in cuerpo
                 if not es_detalle(l) and not es_ruido(l)]
    detalle   = [l.strip() for l in cuerpo if es_detalle(l)]

    # El pie tambien se traduce: `modo: notify_only` no significa nada para
    # quien lee, y `rama: sin rama` es literalmente una linea sin sentido que
    # salia cuando no habia rama que empujar.
    ETIQUETAS = {
        'run:': 'ver detalle:', 'rama:': 'rama:', 'commit:': 'commit:',
        'upstream:': 'proyecto original:', 'modo:': 'seguimiento:',
        'log:': 'ver detalle:', 'ref:': 'rama:',
    }
    VALORES = {
        'notify_only': 'solo avisar',
        'audit_only':  'avisar y revisar',
        'full':        'revisar y desplegar',
        'success':     'bien',
        'failure':     'ha fallado',
        'skipped':     'no aplicaba',
        'cancelled':   'cancelado',
        'sin rama':    None,   # None = se quita la linea entera
    }

    def traducir(linea):
        low = linea.strip().lower()
        for k, v in ETIQUETAS.items():
            if low.startswith(k):
                resto = linea.strip()[len(k):].strip()
                if resto.lower() in VALORES:
                    nv = VALORES[resto.lower()]
                    if nv is None:
                        return None
                    resto = nv
                return f'{v} {resto}'
        for k, v in VALORES.items():
            if v and k in low:
                linea = re.sub(rf'\b{re.escape(k)}\b', v, linea)
        return linea

    detalle = [x for x in (traducir(l) for l in detalle) if x]

    # Los SHA largos del pie se recortan a 12: el resto es ruido visual.
    detalle = [re.sub(r'\b([0-9a-f]{12})[0-9a-f]{8,28}\b', r'\1', l) for l in detalle]

    if explicacion:
        partes.append('')
        partes.append(explicacion)
    if narracion:
        partes.append('')
        partes.extend(narracion)

    accion = ACCIONES.get(estado)
    partes.append('')
    partes.append(accion if accion else 'No hay que hacer nada.')

    if detalle:
        partes.append('')
        partes.append('─────────')
        partes.extend(detalle)
    return '\n'.join(partes)


def salida(nombre, valor):
    destino = os.environ.get('GITHUB_OUTPUT')
    if destino:
        with open(destino, 'a', encoding='utf-8') as fh:
            fh.write(f'{nombre}={valor}\n')


def main():
    token = env('NOTIFY_TOKEN')
    chat = env('NOTIFY_CHAT_ID')
    texto = os.environ.get('NOTIFY_TEXT') or ''
    estado = env('NOTIFY_STATE')
    thread = env('NOTIFY_THREAD_ID')
    topic = env('NOTIFY_TOPIC')
    fichero = env('NOTIFY_TOPICS_FILE')
    en_linea = env('NOTIFY_TOPICS_JSON')
    crear = env('NOTIFY_CREATE_TOPIC', 'false').lower() == 'true'
    parse_mode = env('NOTIFY_PARSE_MODE')
    estricto = env('NOTIFY_STRICT', 'true').lower() == 'true'

    if not token or not chat:
        print('::error::faltan token o chat_id', file=sys.stderr)
        return 1
    if not texto.strip():
        print('::error::el texto del aviso esta vacio', file=sys.stderr)
        return 1
    if estado and estado not in ICONOS:
        print(f'::error::estado desconocido "{estado}"; validos: '
              f'{", ".join(sorted(ICONOS))}', file=sys.stderr)
        return 1

    aviso = None
    if not thread and topic:
        mapa = cargar_mapa(fichero, en_linea)
        thread, aviso = resolver_thread(token, chat, topic, mapa, fichero, crear)

    programa = env('NOTIFY_PROGRAM') or topic
    if estado:
        texto = componer(estado, texto, programa)
    if aviso:
        # Caer al topic General con marca explicita, NUNCA tragarse el mensaje
        # ni crear un duplicado.
        print(f'::warning::{aviso}; se publica en General', file=sys.stderr)
        texto = f'[topic {topic} no disponible] {texto}'
    if len(texto) > LIMITE:
        texto = texto[:LIMITE] + '\n… (truncado)'

    datos = {'chat_id': chat, 'text': texto, 'disable_web_page_preview': True}
    if thread:
        datos['message_thread_id'] = int(thread)
    if parse_mode:
        datos['parse_mode'] = parse_mode

    r = llamar(token, 'sendMessage', datos)
    if not r.get('ok'):
        nivel = 'error' if estricto else 'warning'
        print(f'::{nivel}::Telegram rechazo el mensaje: {r.get("description")}',
              file=sys.stderr)
        return 1 if estricto else 0

    salida('thread_id', thread or '')
    salida('message_id', str(r['result']['message_id']))
    print(f'publicado en {topic or chat} (thread {thread or "General"})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
