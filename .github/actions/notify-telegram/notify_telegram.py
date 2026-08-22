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

    if estado:
        texto = f'{ICONOS[estado]} {texto}'
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
