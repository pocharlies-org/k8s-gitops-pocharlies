#!/usr/bin/env bash
# notify-synapse-monitor.sh — Send a status line to the "Infra" topic (1248)
# of the Pocharlies Operations Telegram supergroup, via the mcp-socialmedia
# telegram-connector. (Name is legacy: until 25-09 this posted to the old
# "Synapse monitor" group, which was retired when all alert streams were
# unified into Infra 1248.)
#
# Why this script exists:
#   The weekly-apt-upgrade timer on each node needs a single, well-tested
#   notification path. Keeping the connector call here means the update
#   scripts stay focused on apt; this script owns one job.
#
# Why it only runs on x86:
#   telegram-connector runs in-cluster (k8s namespace whatsapp-mcp, service
#   `telegram-connector`, port 3002), reachable from any k3s node, and x86 is
#   a node — so a plain curl from x86 reaches it. (The pre-k8s design
#   `docker exec`'d into the connector container; that container is gone.)
#   DGX1/DGX2 call this script via `ssh x86 …`.
#
# Why curl:
#   x86 ships curl natively; no need for the old node one-shot.
#
# Where the connector is:
#   By the DNS name of its Service, so it survives the Service being
#   recreated (a ClusterIP does not). It needs the host to resolve
#   *.cluster.local through CoreDNS; override with CONNECTOR_URL.
#
# How the send is signed (SKIRM-111):
#   /api/public/send/:chatId sits behind the connector's HMAC gate. The request
#   carries x-connector-timestamp and x-connector-signature =
#   sha256=HMAC(key, "<ts>:<body>"), and the connector computes <body> as
#   JSON.stringify of the body it parsed. So the bytes sent must be the bytes
#   JSON.stringify would write: compact, DEL and non-ASCII characters raw.
#   jq is not that (it writes DEL as \u007f and the signature would not match,
#   silently, for a message that has one). So sign_request builds the body and
#   signs that very string with one python3 snippet (json.dumps with
#   ensure_ascii=False, like telegram-sync), and curl sends it unchanged with
#   --data-binary: nothing is serialised twice.
#
# The key (never in git, argv or the log):
#   A file with mode 0600 owned by CONNECTOR_SECRET_OWNER (default dibanez),
#   by default /home/dibanez/.config/notify-synapse-monitor/connector-secret
#   (override: CONNECTOR_SECRET_FILE). It is not under $HOME because the
#   weekly timer runs this as root and the DGX nodes reach it over ssh as
#   dibanez. It holds the CONNECTOR_SHARED_SECRET field of the 1Password item
#   `whatsapp-mcp`, the same value the connector has. Provision it as dibanez
#   on x86 without printing it (the Secret is what the ExternalSecret builds
#   from 1Password, so after a force-sync it is the current value):
#     umask 077
#     mkdir -p ~/.config/notify-synapse-monitor
#     kubectl -n whatsapp-mcp get secret whatsapp-mcp-secrets \
#       -o go-template='{{index .data "CONNECTOR_SHARED_SECRET" | base64decode}}' \
#       > ~/.config/notify-synapse-monitor/connector-secret
#   Check it without printing it: `stat -c '%a %U %s' <file>` and
#   `sha256sum <file> | cut -c1-12`, never `cat`. Repeat after a rotation.
#   A file that is not a regular file, not mode 600 or not owned by the owner
#   is refused. If there is no file at all the script warns and sends
#   unsigned, which works only while the connector does not require a
#   signature.
#
# Usage:
#   notify-synapse-monitor.sh --status ok|warn|fail \
#                             --node <name> \
#                             --summary <text> \
#                             [--reboot-pending]

# sign_request TEXT TOPIC KEYFILE OWNER [TS]
# Prints three things, one per line group: the timestamp, the signature and
# the body (always last, it is the exact string to send and to sign). With an
# empty KEYFILE the timestamp and the signature are empty; with an empty TOPIC
# the body has no topicId. TS is for tests (default: now). The key never
# leaves the python process.
sign_request() {
    printf '%s' "$1" | python3 -I -c '
import hashlib, hmac, json, os, pwd, stat, sys, time

topic, key_file, owner, ts = sys.argv[1:5]
text = sys.stdin.buffer.read().decode("utf-8", "replace")
payload = {"text": text}
if topic:
    payload["topicId"] = int(topic)
body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
sig = ""
if key_file:
    try:
        st = os.stat(key_file)
        if not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode) != 0o600 or pwd.getpwuid(st.st_uid).pw_name != owner:
            sys.exit("refusing " + key_file + ": it must be a regular file, mode 600, owned by " + owner)
        with open(key_file, "rb") as f:
            key = f.read().rstrip(b"\r\n")
    except (OSError, KeyError) as e:
        sys.exit("cannot read " + key_file + ": " + str(e))
    if not key:
        sys.exit(key_file + " is empty")
    ts = ts or str(int(time.time()))
    sig = "sha256=" + hmac.new(key, (ts + ":" + body).encode(), hashlib.sha256).hexdigest()
else:
    ts = ""
sys.stdout.buffer.write((ts + "\n" + sig + "\n" + body).encode())
' "$2" "$3" "$4" "${5:-}"
}

# Sourced (by the tests), only the function above is wanted.
(return 0 2>/dev/null) && return 0

set -uo pipefail

STATUS=""
NODE=""
SUMMARY=""
REBOOT_PENDING=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --status)         STATUS="${2:-}"; shift 2 ;;
        --node)           NODE="${2:-}"; shift 2 ;;
        --summary)        SUMMARY="${2:-}"; shift 2 ;;
        --reboot-pending) REBOOT_PENDING=1; shift ;;
        -h|--help)
            sed -n '2,65p' "$0"
            exit 0 ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 2 ;;
    esac
done

if [[ -z "$STATUS" || -z "$NODE" || -z "$SUMMARY" ]]; then
    echo "Usage: $0 --status ok|warn|fail --node <name> --summary <text> [--reboot-pending]" >&2
    exit 2
fi

case "$STATUS" in
    ok)   EMOJI="✅" ;;
    warn) EMOJI="⚠️" ;;
    fail) EMOJI="❌" ;;
    *)    echo "--status must be ok|warn|fail (got: $STATUS)" >&2; exit 2 ;;
esac

if [[ "$REBOOT_PENDING" == "1" ]]; then
    SUFFIX=" · REBOOT pendiente"
else
    SUFFIX=""
fi

TEXT="${EMOJI} ${NODE}: ${SUMMARY}${SUFFIX}"

# Pocharlies Operations supergroup + Infra forum topic. The connector
# forwards the :chatId path param into mtcute's sendMessage(peer, text,
# topicId); peer is the raw Telegram id (negative for supergroups) and
# topicId is the message_thread_id of the topic.
CHAT_ID="-1004409526898"
TOPIC_ID="1248"

CONNECTOR_URL="${CONNECTOR_URL:-http://telegram-connector.whatsapp-mcp.svc.cluster.local:3002}"
KEY_FILE="${CONNECTOR_SECRET_FILE:-/home/dibanez/.config/notify-synapse-monitor/connector-secret}"
KEY_OWNER="${CONNECTOR_SECRET_OWNER:-dibanez}"

if [[ ! -e "$KEY_FILE" ]]; then
    echo "WARN: no connector key at $KEY_FILE; sending unsigned (the connector rejects that once it requires a signature)." >&2
    KEY_FILE=""
fi

if ! SIGNED=$(sign_request "$TEXT" "$TOPIC_ID" "$KEY_FILE" "$KEY_OWNER"); then
    echo "Notify failed: could not prepare the signed request." >&2
    exit 1
fi
TS="${SIGNED%%$'\n'*}";   SIGNED="${SIGNED#*$'\n'}"
SIG="${SIGNED%%$'\n'*}";  BODY="${SIGNED#*$'\n'}"

CURL_ARGS=(-sS --max-time 10 -X POST -H 'Content-Type: application/json' --data-binary "$BODY")
if [[ -n "$SIG" ]]; then
    CURL_ARGS+=(-H "x-connector-timestamp: $TS" -H "x-connector-signature: $SIG")
fi

RESP=$(curl "${CURL_ARGS[@]}" "$CONNECTOR_URL/api/public/send/$CHAT_ID" 2>&1)
RC=$?

if [[ $RC -eq 0 ]] && [[ "$RESP" == *'"success":true'* ]]; then
    echo "Sent: $TEXT"
    exit 0
fi

echo "Notify failed (rc=$RC). Connector response: ${RESP:-<empty>}" >&2
exit 1
