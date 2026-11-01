#!/usr/bin/env bash
# review-distribute-secrets.sh — reparte POR REPO los secretos que necesita la review con
# PR-Agent (INFRA-298 / INFRA-331). El plan de la org es `free`: un secreto de org no llega a
# los repos privados, así que cada repo lleva su copia (decisión D1 del CTO).
#
# Uso:
#   scripts/review-distribute-secrets.sh --repos r1,r2 [--dry-run] [--rotate]
#                                        [--from-op VAULT/ITEM] [--org pocharlies-org]
#                                        [--secrets A,B]
#
#   --repos       lista separada por comas; `repo` (usa --org) u `owner/repo`. Obligatorio.
#   --dry-run     no escribe nada: dice qué haría por repo y secreto, sin valores.
#   --rotate      sobrescribe también los que ya existen (rotación). Sin él, un secreto
#                 presente no se toca: reejecutar es idempotente.
#   --secrets     qué repartir, separado por comas, de PR_AGENT_LITELLM_KEY, JIRA_EMAIL, JIRA_API_TOKEN
#                 y BRAIN_CI_KEY (PR-Agent, el juego por defecto) y LITELLM_JUEZ_KEY, JIRA_JUEZ_EMAIL,
#                 JIRA_JUEZ_TOKEN, JIRA_JUEZ_URL (el juez, SC-2182):
#                 --secrets LITELLM_JUEZ_KEY,JIRA_JUEZ_EMAIL,JIRA_JUEZ_TOKEN,JIRA_JUEZ_URL.
#   --from-op     item de 1Password por Connect, como `k8s-pocharlies/pr-review-ci`; los campos del
#                 item se llaman igual que el secreto (vale id o etiqueta, sin distinguir mayúsculas).
#                 Necesita OP_CONNECT_HOST y OP_CONNECT_TOKEN en el entorno (el token viaja a curl
#                 por `-H @fichero` 0600, nunca en su argv). [GOTCHA: el viejo `--from-vault` apuntaba
#                 a Vault, retirado en SC-699; los valores viven en el item 1Password
#                 k8s-pocharlies/pr-review-ci desde el veredicto de security de SC-1400 (INFRA-1055).]
#
# Valor de cada secreto: la variable de entorno del mismo nombre si está puesta; si no,
# el item de 1Password (--from-op). Nunca por argumento, nunca impreso: viaja por stdin a `gh secret set`.
#
# Salida: una línea `clave=valor` por repo y secreto, y una línea RESUMEN al final.
# Códigos: 0 hecho (o plan en --dry-run) · 2 uso inválido, repo inexistente o valor ausente
# (en ese caso no se escribe nada) · 4 la API de GitHub o Connect respondió 401/403, o el token
# no es admin ni tiene `secrets: write` en el repo · 1 cualquier otro fallo de la API.
#
# Permisos del token: basta `.permissions.secrets == "write"` (PAT fine-grained `Secrets: write` +
# `Metadata: read`, exigido por security antes de la oleada, SC-1400); `admin` del repo también vale.
# BRAIN_CI_KEY: autorizada por security SOLO en los 2 pilotos (INFRA-1055); la oleada a los 108
# repos espera INFRA-1059 (clave de instancia del brain) e INFRA-1058 (cuenta Jira + PAT).
set -Eeuo pipefail
set +x 2>/dev/null || true

SECRETS=(PR_AGENT_LITELLM_KEY JIRA_EMAIL JIRA_API_TOKEN BRAIN_CI_KEY)
KNOWN=" PR_AGENT_LITELLM_KEY JIRA_EMAIL JIRA_API_TOKEN BRAIN_CI_KEY LITELLM_JUEZ_KEY JIRA_JUEZ_EMAIL JIRA_JUEZ_TOKEN JIRA_JUEZ_URL "

ORG="pocharlies-org"; REPOS=""; DRY=0; ROTATE=0; OP_ITEM=""

usage() { awk 'NR>1 && /^#/{sub(/^# ?/,""); print; next} NR>1{exit}' "$0" >&2; exit 2; }
die() { echo "ERROR: $1" >&2; exit "${2:-2}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --repos) REPOS="${2:-}"; shift 2 ;;
    --org) ORG="${2:-}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --rotate) ROTATE=1; shift ;;
    --secrets) IFS=',' read -r -a SECRETS <<< "${2:-}"; shift 2 ;;
    --from-op) OP_ITEM="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "argumento desconocido: $1" >&2; usage ;;
  esac
done
[ -n "$REPOS" ] || { echo "falta --repos" >&2; usage; }
[ "${#SECRETS[@]}" -gt 0 ] || die "--secrets vacío"
for name in "${SECRETS[@]}"; do [[ "$KNOWN" == *" $name "* ]] || die "secreto desconocido: $name"; done
[[ "$ORG" =~ ^[A-Za-z0-9._-]+$ ]] || die "org inválida: $ORG"
if [ -n "$OP_ITEM" ]; then
  [[ "$OP_ITEM" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]] || die "--from-op necesita VAULT/ITEM (p. ej. k8s-pocharlies/pr-review-ci)"
  { [ -n "${OP_CONNECT_HOST:-}" ] && [ -n "${OP_CONNECT_TOKEN:-}" ]; } || die "--from-op necesita OP_CONNECT_HOST y OP_CONNECT_TOKEN"
  case "$OP_CONNECT_HOST" in
    https://*|http://localhost*|http://127.0.0.1*) : ;;
    *) die "OP_CONNECT_HOST debe ser https:// (o http://localhost|127.0.0.1 para port-forward): $OP_CONNECT_HOST" ;;
  esac
fi

TMPD=$(mktemp -d); chmod 700 "$TMPD"; trap 'rm -rf "$TMPD"' EXIT INT TERM

# status HTTP de un fallo de `gh api` (texto «HTTP 404» en stderr); vacío si no lo hay
http_status() { grep -oE 'HTTP [0-9]{3}' "$1" | tail -1 | cut -d' ' -f2 || true; }

# ---- valores: se cargan una vez en ficheros 0600 del directorio temporal ------------------
# 1Password Connect (patrón DGX-1085): GET /v1/vaults → id por nombre; GET /v1/vaults/<id>/items
# → id del item por título; GET /v1/vaults/<id>/items/<item> → campos (la lista no los da); el
# campo cuyo id o etiqueta (sin distinguir mayúsculas) es el secreto. Nunca se imprime un valor:
# jq lo escribe directo en el fichero 0600 y de ahí viaja por stdin a gh.
OP_JSON="$TMPD/op.json"
if [ -n "$OP_ITEM" ]; then
  op_vault="${OP_ITEM%%/*}"; op_item="${OP_ITEM#*/}"
  # El token nunca va en el argv de curl (lo vería cualquiera con `ps`): lo escribe printf, que
  # es builtin, en un fichero 0600 de $TMPD (0700) y curl lo lee con -H @fichero.
  case "$OP_CONNECT_TOKEN" in *$'\n'*|*$'\r'*) die "OP_CONNECT_TOKEN inválido: lleva saltos de línea" ;; esac
  OP_HDR="$TMPD/op.hdr"
  (umask 077; printf 'Authorization: Bearer %s\n' "$OP_CONNECT_TOKEN" > "$OP_HDR")
  op_get() { # op_get <ruta> <fichero-salida> <etiqueta-de-error>
    local code
    code=$(curl -sS -o "$2" -w '%{http_code}' -H "@$OP_HDR" "$OP_CONNECT_HOST$1" 2>"$TMPD/curl.err" || echo 000)
    case "$code" in
      200) ;;
      401|403) rm -f "$OP_HDR"; die "Connect respondió $code en $3" 4 ;;
      *) rm -f "$OP_HDR"; die "Connect no respondió bien (http=$code) en $3" 1 ;;
    esac
  }
  op_get "/v1/vaults" "$TMPD/vaults.json" "GET /v1/vaults"
  if ! OP_VAULT_ID=$(jq -r --arg v "$op_vault" '[.[] | select(.name == $v)][0].id // empty' "$TMPD/vaults.json"); then
    rm -f "$OP_HDR"; die "Connect devolvió un JSON ilegible en /v1/vaults" 1
  fi
  [ -n "$OP_VAULT_ID" ] || die "no existe el vault $op_vault en Connect (¿token sin alcance?)" 2
  # [GOTCHA medido 2026-10-31] el endpoint de lista NO devuelve los campos de los items (y `q`
  # no filtra: devuelve el vault entero). El valor de un campo CONCEALED solo lo da el GET del
  # item: se busca el id por título en la lista y se pide el item completo.
  op_get "/v1/vaults/$OP_VAULT_ID/items" "$TMPD/items.json" "GET items de $op_vault"
  if ! OP_ITEM_ID=$(jq -r --arg t "$op_item" '[.[] | select(.title == $t)][0].id // empty' "$TMPD/items.json"); then
    rm -f "$OP_HDR"; die "Connect devolvió un JSON ilegible en los items de $op_vault" 1
  fi
  [ -n "$OP_ITEM_ID" ] || die "no existe el item $op_item en el vault $op_vault" 2
  op_get "/v1/vaults/$OP_VAULT_ID/items/$OP_ITEM_ID" "$OP_JSON" "GET item $op_item"
  rm -f "$OP_HDR"
fi
declare -A SOURCE=()
for name in "${SECRETS[@]}"; do
  f="$TMPD/val.$name"; : > "$f"; chmod 600 "$f"
  lname=$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]')
  if [ -n "${!name:-}" ]; then
    printf '%s' "${!name}" > "$f"; SOURCE[$name]=env
  elif [ -n "$OP_ITEM" ] && jq -e --arg k "$lname" \
      '[.fields[]?
        | select(((.id // "") | ascii_downcase) == $k or ((.label // "") | ascii_downcase) == $k)
        | select((.value // "") != "")] | length > 0' "$OP_JSON" >/dev/null 2>&1; then
    jq -j --arg k "$lname" \
      '[.fields[]?
        | select(((.id // "") | ascii_downcase) == $k or ((.label // "") | ascii_downcase) == $k)
        | select((.value // "") != "")][0].value' "$OP_JSON" > "$f"; SOURCE[$name]=op
  else
    SOURCE[$name]=ausente
  fi
done

# ---- plan: estado actual de cada repo (solo nombres; GitHub no devuelve valores) ----------
IFS=',' read -r -a LIST <<< "$REPOS"
declare -a PLAN=()
missing=0
for raw in "${LIST[@]}"; do
  r="${raw//[[:space:]]/}"; [ -n "$r" ] || continue
  [[ "$r" == */* ]] || r="$ORG/$r"
  [[ "$r" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]] || die "repo inválido: $raw"
  # El PAT de reparto es fine-grained `Secrets: write` + `Metadata: read` (SC-1400): basta
  # `.permissions.secrets == "write"`; `admin` del repo también vale (token personal).
  if ! perms=$(gh api "repos/$r" --jq '[.permissions.admin, .permissions.secrets] | @tsv' 2>"$TMPD/err"); then
    st=$(http_status "$TMPD/err")
    case "$st" in
      401|403) die "GitHub respondió $st al leer $r" 4 ;;
      404) die "repo inexistente o fuera del alcance del token: $r" 2 ;;
      *) die "fallo leyendo $r: $(head -c 200 "$TMPD/err")" 1 ;;
    esac
  fi
  IFS=$'\t' read -r admin secrets_perm <<< "$perms"
  { [ "$admin" = "true" ] || [ "$secrets_perm" = "write" ]; } || \
    die "el token no es admin de $r ni tiene secrets: write (tiene: admin=$admin secrets=${secrets_perm:-ninguno}): no puede escribir sus secretos" 4
  if ! gh api --paginate "repos/$r/actions/secrets" --jq '.secrets[].name' > "$TMPD/names" 2>"$TMPD/err"; then
    st=$(http_status "$TMPD/err")
    case "$st" in 401|403) die "GitHub respondió $st al listar secretos de $r" 4 ;; *) die "fallo listando secretos de $r" 1 ;; esac
  fi
  for name in "${SECRETS[@]}"; do
    if grep -qxF "$name" "$TMPD/names"; then
      estado=presente; if [ "$ROTATE" = 1 ]; then accion=rotar; else accion=ya-presente; fi
    else
      estado=ausente; accion=crear
    fi
    if [ "$accion" != ya-presente ] && [ "${SOURCE[$name]}" = ausente ]; then missing=$((missing+1)); fi
    PLAN+=("$r $name $estado $accion")
  done
done
[ "${#PLAN[@]}" -gt 0 ] || die "--repos no trae ningún repo"
n_repos=$(( ${#PLAN[@]} / ${#SECRETS[@]} ))

modo=real; [ "$DRY" = 1 ] && modo=dry-run
if [ "$DRY" = 0 ] && [ "$missing" -gt 0 ]; then
  for p in "${PLAN[@]}"; do
    read -r r name estado accion <<< "$p"
    [ "$accion" != ya-presente ] && [ "${SOURCE[$name]}" = ausente ] && \
      echo "repo=$r secreto=$name estado=$estado accion=$accion fuente=ausente resultado=bloqueado"
  done
  echo "RESUMEN modo=$modo repos=$n_repos faltan-valores=$missing escritos=0"
  die "faltan $missing valores (variable de entorno o --from-op): no se ha escrito nada" 2
fi

# ---- ejecución ---------------------------------------------------------------------------
n_crear=0; n_rotar=0; n_pres=0; n_err=0; auth=0
for p in "${PLAN[@]}"; do
  read -r r name estado accion <<< "$p"
  line="repo=$r secreto=$name estado=$estado accion=$accion fuente=${SOURCE[$name]}"
  case "$accion" in crear) n_crear=$((n_crear+1)) ;; rotar) n_rotar=$((n_rotar+1)) ;; *) n_pres=$((n_pres+1)) ;; esac
  if [ "$DRY" = 1 ] || [ "$accion" = ya-presente ]; then
    echo "$line modo=$modo"; continue
  fi
  if gh secret set "$name" --repo "$r" < "$TMPD/val.$name" >/dev/null 2>"$TMPD/err"; then
    echo "$line resultado=ok"
  else
    st=$(http_status "$TMPD/err"); n_err=$((n_err+1))
    case "$st" in 401|403) auth=1 ;; esac
    echo "$line resultado=error http=${st:-?}"
  fi
done
echo "RESUMEN modo=$modo repos=$n_repos crear=$n_crear rotar=$n_rotar ya-presente=$n_pres errores=$n_err"
[ "$auth" = 1 ] && exit 4
[ "$n_err" -gt 0 ] && exit 1
exit 0
