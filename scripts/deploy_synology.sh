#!/usr/bin/env bash
# Deploy MAI-IDX-Signal to Synology NAS via SSH.
# Run from Hermes or any host with LAN/Tailscale access to 192.168.1.20.
#
# Usage:
#   chmod +x scripts/deploy_synology.sh
#   ./scripts/deploy_synology.sh
#
# Prerequisites:
#   - SSH key at /opt/data/home/.ssh/id_ed25519 (or SSH_KEY_PATH env)
#   - docker-compose.yml at /volume1/docker/mai-idx-signal/ on the NAS
#   - .env file at /volume1/docker/mai-idx-signal/.env on the NAS (never committed)

set -euo pipefail

NAS_HOST="${NAS_HOST:-192.168.1.20}"
NAS_USER="${NAS_USER:-hermes}"
SSH_KEY="${SSH_KEY_PATH:-/opt/data/home/.ssh/id_ed25519}"
COMPOSE_PATH="/volume1/docker/mai-idx-signal/docker-compose.yml"
HEALTH_URL="http://${NAS_HOST}:7843/health"

echo "==> Deploying MAI-IDX-Signal to ${NAS_HOST}..."

ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no "${NAS_USER}@${NAS_HOST}" bash <<EOF
  set -e
  sudo /usr/local/bin/docker compose -f ${COMPOSE_PATH} pull
  sudo /usr/local/bin/docker compose -f ${COMPOSE_PATH} up -d --remove-orphans
  sleep 5
  curl -sf ${HEALTH_URL} && echo " HEALTH OK" || echo " HEALTH CHECK FAILED"
EOF

echo "==> Deploy complete."
echo "    Dashboard: http://${NAS_HOST}:7843/dashboard"
echo "    API:       http://${NAS_HOST}:7843/api/signals/latest"
