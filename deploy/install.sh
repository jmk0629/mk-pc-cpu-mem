#!/usr/bin/env bash
# mk-pc-cpu-mem 설치 스크립트 (크로스플랫폼: Linux=systemd / macOS=launchd)
# 사용: sudo ./deploy/install.sh   (Linux)  |  ./deploy/install.sh  (macOS user agent)
set -euo pipefail

APP_DIR="/opt/pc-monitor"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OS="$(uname -s)"

echo "==> mk-pc-cpu-mem 설치 (OS=$OS, repo=$REPO_DIR)"

# 1) 앱 디렉터리 + 소스 복사
sudo_if() { if [ "$OS" = "Linux" ]; then sudo "$@"; else "$@"; fi; }
sudo_if mkdir -p "$APP_DIR"
sudo_if cp -R "$REPO_DIR/src" "$APP_DIR/"
[ -f "$APP_DIR/config.yaml" ] || sudo_if cp "$REPO_DIR/config.yaml.example" "$APP_DIR/config.yaml"

# 2) 가상환경 + 의존성
sudo_if python3 -m venv "$APP_DIR/venv"
sudo_if "$APP_DIR/venv/bin/pip" install -q -r "$REPO_DIR/requirements.txt"
# PYTHONPATH 대신 src 를 venv 에서 인식하도록 .pth 추가
echo "$APP_DIR/src" | sudo_if tee "$APP_DIR/venv/lib/"python*/site-packages/pcmon.pth >/dev/null

echo "==> config.yaml 에 telegram.token / chat_ids / targets 를 채우세요: $APP_DIR/config.yaml"

# 3) 서비스 등록
if [ "$OS" = "Linux" ]; then
  sudo cp "$REPO_DIR/deploy/systemd/"pc-*.{service,timer} /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable --now pc-monitor.service
  sudo systemctl enable --now pc-watchdog.timer
  echo "==> 완료. 상태: systemctl status pc-monitor / journalctl -u pc-monitor -f"
elif [ "$OS" = "Darwin" ]; then
  AGENTS="$HOME/Library/LaunchAgents"
  mkdir -p "$AGENTS"
  cp "$REPO_DIR/deploy/launchd/"com.mkpc.*.plist "$AGENTS/"
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/com.mkpc.monitor.plist" 2>/dev/null || \
    launchctl load "$AGENTS/com.mkpc.monitor.plist"
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/com.mkpc.watchdog.plist" 2>/dev/null || \
    launchctl load "$AGENTS/com.mkpc.watchdog.plist"
  echo "==> 완료. 로그: tail -f /tmp/pcmon-monitor.log"
else
  echo "지원하지 않는 OS: $OS"; exit 1
fi
