#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/waleed-might-code/codex-session.git}"
BRANCH="${BRANCH:-main}"
APP_DIR="${APP_DIR:-/opt/codex-session}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SERVICE_NAME="${SERVICE_NAME:-codex-session}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root or with sudo."
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y \
  git \
  curl \
  ca-certificates \
  python3 \
  python3-venv \
  python3-pip \
  unzip \
  jq \
  build-essential \
  libnss3 \
  libnspr4 \
  libatk1.0-0 \
  libatk-bridge2.0-0 \
  libcups2 \
  libdrm2 \
  libdbus-1-3 \
  libxkbcommon0 \
  libxcomposite1 \
  libxdamage1 \
  libxfixes3 \
  libxrandr2 \
  libgbm1 \
  libasound2t64 || apt-get install -y libasound2

mkdir -p "$(dirname "${APP_DIR}")"

if [[ -d "${APP_DIR}/.git" ]]; then
  git -C "${APP_DIR}" fetch origin
  git -C "${APP_DIR}" checkout "${BRANCH}"
  git -C "${APP_DIR}" pull --ff-only origin "${BRANCH}"
else
  git clone --branch "${BRANCH}" "${REPO_URL}" "${APP_DIR}"
fi

cd "${APP_DIR}"
"${PYTHON_BIN}" -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

cat >/etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=Codex Session Discord Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"

echo
echo "Install complete."
echo "Next steps:"
echo "  1. Edit ${APP_DIR}/.env"
echo "  2. Run: cd ${APP_DIR} && . .venv/bin/activate && python register_commands.py"
echo "  3. Start: systemctl restart ${SERVICE_NAME}"
echo "  4. Logs:  journalctl -u ${SERVICE_NAME} -f"
