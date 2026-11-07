#!/usr/bin/env bash
# TokenPulse: monitor in its own app window (Chromium / Chrome / Edge), no tabs or address bar.
#   ./start-monitor.sh                              this computer, http://127.0.0.1:8787
#   ./start-monitor.sh http://192.168.31.30:8787    a server on the network
#   ./start-monitor.sh http://192.168.31.30:8787 mini   compact strip from the start
#   ./start-monitor.sh http://192.168.31.30:8787 full crt    skin: pulse, crt, paper, neon, mono
SERVER="${1:-http://127.0.0.1:8787}"
case "$SERVER" in http*) ;; *) SERVER="http://$SERVER" ;; esac
SKIN="${3:+skin=$3}"; URL="$SERVER/?$SKIN"; SIZE="380,850"
if [ "$2" = "mini" ]; then URL="$SERVER/?mini=1&$SKIN"; SIZE="380,150"; fi
PROFILE="${XDG_CONFIG_HOME:-$HOME/.config}/tokenpulse-app"
for b in chromium chromium-browser google-chrome google-chrome-stable microsoft-edge brave-browser; do
  if command -v "$b" >/dev/null 2>&1; then
    exec "$b" --app="$URL" --window-size="$SIZE" --user-data-dir="$PROFILE" --no-first-run >/dev/null 2>&1
  fi
done
echo "Chromium/Chrome/Edge not found, opening the default browser"
xdg-open "$URL" >/dev/null 2>&1 || echo "open $URL"
