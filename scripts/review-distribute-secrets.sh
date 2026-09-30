#!/usr/bin/env bash
# review-distribute-secrets.sh — reparte POR REPO los secretos que necesita la review con
# PR-Agent (INFRA-298 / INFRA-331). El plan de la org es `free`: un secreto de org no llega a
# los repos privados, así que cada repo lleva su copia (decisión D1 del CTO).
#
# Uso:
#   scripts/review-distribute-secrets.sh --repos r1,r2 [--dry-run] [--rotate]
#                                        [--from-vault RUTA] [--org pocharlies-org]
#
#   --repos       lista separada por comas; `repo` (usa --org) u `owner/repo`. Obligatorio.
#   --dry-run     no escribe nada: dice qué haría por repo y secreto, sin valores.
#   --rotate      sobrescribe también los que ya existen (rotación). Sin él, un secreto
#                 presente no se toca: reejecutar es idempotente.
#   --from-vault  ruta KV v2 bajo el montaje `secret/` (p. ej. pr-review-ci); las claves se
#                 llaman igual que el secreto. Necesita VAULT_ADDR y VAULT_TOKEN en el entorno.
#
# Valor de cada secreto: la variable de entorno del mismo nombre si está puesta; si no,
# Vault (--from-vault). Nunca por argumento, nunca impreso: viaja por stdin a `gh secret set`.
#
# Salida: una línea `clave=valor` por repo y secreto, y una línea RESUMEN al final.
# Códigos: 0 hecho (o plan en --dry-run) · 2 uso inválido, repo inexistente o valor ausente
# (en ese caso no se escribe nada) · 4 la API de GitHub o Vault respondió 401/403 ·
# 1 cualquier otro fallo de la API.
#
# BRAIN_CI_KEY no está en la lista a propósito: pendiente de security (Request SC-1400, B1).
set -Eeuo pipefail
set +x 2>/dev/null || true

SECRETS=(PR_AGENT_LITELLM_KEY JIRA_EMAIL JIRA_API_TOKEN)
KV_MOUNT="${KV_MOUNT:-secret}"

ORG="pocharlies-org"; REPOS=""; DRY=0; ROTATE=0; VAULT_PATH=""

usage() { sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
die() { echo "ERROR: $1" >&2; exit "${2:-2}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --repos) REPOS="${2:-}"; shift 2 ;;
    --org) ORG="${2:-}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --rotate) ROTATE=1; shift ;;
    --from-vault) VAULT_PATH="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "argumento desconocido: $1" >&2; usage ;;
  esac
done
[ -n "$REPOS" ] || { echo "falta --repos" >&2; usage; }
[[ "$ORG" =~ ^[A-Za-z0-9._-]+$ ]] || die "org inválida: $ORG"
if [ -n "$VAULT_PATH" ]; then
  [[ "$VAULT_PATH" =~ ^[A-Za-z0-9._/-]+$ ]] || die "ruta de Vault inválida: $VAULT_PATH"
  [ -n "${VAULT_ADDR:-}" ] && [ -n "${VAULT_TOKEN:-}" ] || die "--from-vault necesita VAULT_ADDR y VAULT_TOKEN"
fi

TMPD=$(mktemp -d); chmod 700 "$TMPD"; trap 'rm -rf "$TMPD"' EXIT INT TERM

# status HTTP de un fallo de `gh api` (texto «HTTP 404» en stderr); vacío si no lo hay
http_status() { grep -oE 'HTTP [0-9]{3}' "$1" | tail -1 | cut -d' ' -f2 || true; }

# ---- valores: se cargan una vez en ficheros 0600 del directorio temporal ------------------
VAULT_JSON="$TMPD/vault.json"
if [ -n "$VAULT_PATH" ]; then
  code=$(curl -sS -o "$VAULT_JSON" -w '%{http_code}' -H "X-Vault-Token: $VAULT_TOKEN" \
    "$VAULT_ADDR/v1/$KV_MOUNT/data/$VAULT_PATH" 2>"$TMPD/curl.err" || echo 000)
  case "$code" in
    200) ;;
    404) echo '{}' > "$VAULT_JSON" ;;
    401|403) die "Vault respondió $code en $KV_MOUNT/$VAULT_PATH" 4 ;;
    *) die "Vault no respondió bien (http=$code) en $KV_MOUNT/$VAULT_PATH" 1 ;;
  esac
fi
declare -A SOURCE=()
for name in "${SECRETS[@]}"; do
  f="$TMPD/val.$name"; : > "$f"; chmod 600 "$f"
  if [ -n "${!name:-}" ]; then
    printf '%s' "${!name}" > "$f"; SOURCE[$name]=env
  elif [ -n "$VAULT_PATH" ] && jq -e --arg k "$name" '(.data.data // {})[$k] // "" | length > 0' "$VAULT_JSON" >/dev/null 2>&1; then
    jq -j --arg k "$name" '.data.data[$k]' "$VAULT_JSON" > "$f"; SOURCE[$name]=vault
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
  if ! admin=$(gh api "repos/$r" --jq '.permissions.admin' 2>"$TMPD/err"); then
    st=$(http_status "$TMPD/err")
    case "$st" in
      401|403) die "GitHub respondió $st al leer $r" 4 ;;
      404) die "repo inexistente o fuera del alcance del token: $r" 2 ;;
      *) die "fallo leyendo $r: $(head -c 200 "$TMPD/err")" 1 ;;
    esac
  fi
  [ "$admin" = "true" ] || die "el token no es admin de $r: no puede escribir sus secretos" 4
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
  die "faltan $missing valores (variable de entorno o --from-vault): no se ha escrito nada" 2
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
