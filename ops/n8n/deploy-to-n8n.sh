#!/usr/bin/env bash
# Import and publish the GengoWatcher n8n workflows on the n8n host (default: vps2).
#
# Idempotent: workflows and credentials keep fixed IDs, so re-running updates them in
# place, and the setup workflow reuses an existing gengo_jobs Data Table.
#
# Usage:
#   ops/n8n/deploy-to-n8n.sh --dry-run            # print every remote command, run nothing
#   ops/n8n/deploy-to-n8n.sh                      # asks for confirmation first
#   ops/n8n/deploy-to-n8n.sh --yes                # no prompt
#   ops/n8n/deploy-to-n8n.sh --with-credentials   # also import the 2 Gengo credentials from env
#   ops/n8n/deploy-to-n8n.sh --skip-setup         # do not trigger the Data Table setup
#
# --with-credentials reads these variables from the environment (never from files, never
# echoed, sent over ssh stdin only):
#   N8N_WEBHOOK_TOKEN          value of header X-Daweuchi-Token (router -> n8n)
#   EVENT_PUBLISH_TOKEN        Daweuchi event bus bearer token (n8n -> bus)
#
# Matrix alerts reuse the existing n8n credential matrixNotifyBot0 ("Matrix notify bot
# (@journal)", Bearer = as_token of /docker/matrix/data/appservices/notify.yaml on vps1),
# created by ~/Projects/daweuchi-local/trading/n8n/deploy.py. This script never touches it.
#
# Overrides: N8N_SSH_HOST (vps2), N8N_CONTAINER (n8n-n8n-1), N8N_COMPOSE_DIR (/opt/n8n),
# N8N_COMPOSE_SERVICE (n8n), N8N_PUBLIC_URL (https://n8n.daweuchi.com),
# DAWEUCHI_AUTOMATION_DIR (~/Projects/daweuchi-local/automation, for publish-event).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSH_HOST="${N8N_SSH_HOST:-vps2}"
CONTAINER="${N8N_CONTAINER:-n8n-n8n-1}"
COMPOSE_DIR="${N8N_COMPOSE_DIR:-/opt/n8n}"
COMPOSE_SERVICE="${N8N_COMPOSE_SERVICE:-n8n}"
PUBLIC_URL="${N8N_PUBLIC_URL:-https://n8n.daweuchi.com}"
AUTOMATION_DIR="${DAWEUCHI_AUTOMATION_DIR:-$HOME/Projects/daweuchi-local/automation}"
REMOTE_DIR="/tmp/gengo-n8n-import"

# Import order matters only for readability; publish order puts the Matrix alert
# sub-workflow first because the other workflows call its published version.
WORKFLOW_FILES=(
  gengo-setup-datatable.workflow.json
  gengo-matrix-alert.workflow.json
  gengo-job-pipeline.workflow.json
  gengo-approval-form.workflow.json
)
PUBLISH_IDS=(gengoWfMatrx0002 gengoWfSetup0001 gengoWfPipe00003 gengoWfAppr00004)

DRY_RUN=0
ASSUME_YES=0
WITH_CREDENTIALS=0
SKIP_SETUP=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --yes | -y) ASSUME_YES=1 ;;
    --with-credentials) WITH_CREDENTIALS=1 ;;
    --skip-setup) SKIP_SETUP=1 ;;
    -h | --help)
      sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "unknown option: $arg" >&2
      exit 2
      ;;
  esac
done

log() { printf '==> %s\n' "$*"; }

# Run a command on the n8n host. In dry-run mode only print it.
remote() {
  if ((DRY_RUN)); then
    printf '[dry-run] ssh %s "%s"\n' "$SSH_HOST" "$1"
  else
    ssh "$SSH_HOST" "$1"
  fi
}

n8n_cli() {
  remote "docker exec $CONTAINER n8n $*"
}

log "Validating workflow JSON"
for file in "${WORKFLOW_FILES[@]}"; do
  python3 -m json.tool "$HERE/$file" >/dev/null
done

if ((WITH_CREDENTIALS)); then
  for var in N8N_WEBHOOK_TOKEN EVENT_PUBLISH_TOKEN; do
    if [[ -z "${!var:-}" ]]; then
      echo "--with-credentials needs $var in the environment" >&2
      exit 2
    fi
  done
fi

if ((!DRY_RUN && !ASSUME_YES)); then
  read -r -p "Import + publish 4 Gengo workflows into $SSH_HOST:$CONTAINER and restart it? [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]] || {
    echo "aborted"
    exit 1
  }
fi

log "Copying workflows to $SSH_HOST:$CONTAINER:$REMOTE_DIR"
remote "docker exec $CONTAINER sh -c 'rm -rf $REMOTE_DIR && mkdir -p $REMOTE_DIR'"
for file in "${WORKFLOW_FILES[@]}"; do
  if ((DRY_RUN)); then
    printf '[dry-run] ssh %s docker exec -i %s sh -c "cat > %s/%s" < %s\n' \
      "$SSH_HOST" "$CONTAINER" "$REMOTE_DIR" "$file" "$HERE/$file"
  else
    ssh "$SSH_HOST" "docker exec -i $CONTAINER sh -c 'cat > $REMOTE_DIR/$file'" <"$HERE/$file"
  fi
done

if ((WITH_CREDENTIALS)); then
  log "Importing credentials (values from environment, not printed)"
  if ((DRY_RUN)); then
    printf '[dry-run] ssh %s docker exec -i %s sh -c "umask 077; cat > %s/credentials.json" < <generated>\n' \
      "$SSH_HOST" "$CONTAINER" "$REMOTE_DIR"
  else
    # python3 builds the JSON so secrets are escaped correctly and never hit argv.
    python3 - <<'PY' | ssh "$SSH_HOST" "docker exec -i $CONTAINER sh -c 'umask 077; cat > $REMOTE_DIR/credentials.json'"
import json, os
print(json.dumps([
    {"id": "daweuchiWebhookHdr", "name": "Daweuchi Webhook Header Token",
     "type": "httpHeaderAuth",
     "data": {"name": "X-Daweuchi-Token", "value": os.environ["N8N_WEBHOOK_TOKEN"]}},
    {"id": "daweuchiEventBusBr", "name": "Daweuchi Event Bus Bearer Token",
     "type": "httpBearerAuth", "data": {"token": os.environ["EVENT_PUBLISH_TOKEN"]}},
]))
PY
  fi
  n8n_cli "import:credentials --input=$REMOTE_DIR/credentials.json"
  remote "docker exec $CONTAINER rm -f $REMOTE_DIR/credentials.json"
fi

log "Importing workflows"
for file in "${WORKFLOW_FILES[@]}"; do
  n8n_cli "import:workflow --input=$REMOTE_DIR/$file"
done

log "Publishing workflows"
for id in "${PUBLISH_IDS[@]}"; do
  n8n_cli "publish:workflow --id=$id"
done

log "Restarting n8n so published versions and webhooks take effect"
remote "cd $COMPOSE_DIR && docker compose restart $COMPOSE_SERVICE"
remote "for i in \$(seq 1 60); do docker exec $CONTAINER wget -q -O /dev/null http://127.0.0.1:5678/healthz && exit 0; sleep 2; done; echo 'n8n did not become healthy' >&2; exit 1"
remote "docker exec $CONTAINER rm -rf $REMOTE_DIR"

if ((SKIP_SETUP)); then
  log "Skipping Data Table setup (--skip-setup)"
else
  # `n8n execute` does not load the data-table module in 2.45.5, so the setup workflow
  # is triggered through its header-authenticated webhook instead (idempotent).
  log "Creating/reusing the gengo_jobs Data Table"
  if ((DRY_RUN)); then
    echo "[dry-run] POST $PUBLIC_URL/webhook/gengo-setup-datatable (X-Daweuchi-Token)"
  elif [[ -n "${N8N_WEBHOOK_TOKEN:-}" ]]; then
    curl -fsS -X POST -H 'Content-Type: application/json' \
      -H "X-Daweuchi-Token: $N8N_WEBHOOK_TOKEN" -d '{}' \
      "$PUBLIC_URL/webhook/gengo-setup-datatable" | python3 -c \
      'import json,sys; d=json.load(sys.stdin); print("data table:", d.get("name"), d.get("id"))'
  elif [[ -x "$AUTOMATION_DIR/publish-event" ]]; then
    # The router's forward-to-n8n rule turns workflows/<path> into /webhook/<path>.
    "$AUTOMATION_DIR/publish-event" workflows/gengo-setup-datatable '{}'
    echo "Published workflows/gengo-setup-datatable; check the n8n executions list."
  else
    echo "Set N8N_WEBHOOK_TOKEN or open 'Gengo — 00 Setup Data Table' and execute it once." >&2
  fi
fi

log "Done. Webhook: $PUBLIC_URL/webhook/gengo-events  Form: $PUBLIC_URL/form/gengo-approval"
