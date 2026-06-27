#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
APP_TEMPLATE="$ROOT_DIR/deploy/systemd/rag-resume-customizer.service.template"
APP_UNIT="$SYSTEMD_USER_DIR/rag-resume-customizer.service"
TUNNEL_TEMPLATE="$ROOT_DIR/deploy/systemd/ragume-cloudflared.service.template"
TUNNEL_UNIT="$SYSTEMD_USER_DIR/ragume-cloudflared.service"
TUNNEL_CONFIG="$ROOT_DIR/deploy/cloudflared/ragume.yml"

mkdir -p "$SYSTEMD_USER_DIR"

render_template() {
  local template_path="$1"
  local output_path="$2"
  sed "s|__PROJECT_DIR__|$ROOT_DIR|g" "$template_path" > "$output_path"
}

render_template "$APP_TEMPLATE" "$APP_UNIT"

INSTALL_TUNNEL="false"
if [[ -f "$TUNNEL_CONFIG" ]]; then
  render_template "$TUNNEL_TEMPLATE" "$TUNNEL_UNIT"
  INSTALL_TUNNEL="true"
fi

if command -v systemctl >/dev/null 2>&1; then
  systemctl --user daemon-reload
  systemctl --user enable --now rag-resume-customizer.service
  if [[ "$INSTALL_TUNNEL" == "true" ]]; then
    systemctl --user enable --now ragume-cloudflared.service
  fi
fi

echo "Installed rag-resume-customizer.service to $APP_UNIT"
if [[ "$INSTALL_TUNNEL" == "true" ]]; then
  echo "Installed ragume-cloudflared.service to $TUNNEL_UNIT"
else
  echo "Skipped Cloudflare tunnel unit because $TUNNEL_CONFIG does not exist yet."
fi
echo "If you want the user services to survive reboots before login, run:"
echo "  sudo loginctl enable-linger $USER"
