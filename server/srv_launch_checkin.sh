#!/bin/bash
# Manual/debug launcher: same env as cron wrapper but no jitter sleep and no IP rotation.
set -u
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
REPO=/home/shenhao/anyrouter-check-in
cd "$REPO" || exit 1

# Share the single-instance lock with run_backup_checkin.sh.
LOCKFILE=/tmp/anyrouter_checkin.lock
exec 9>"$LOCKFILE"
if ! flock -n 9; then
  echo "another check-in run is already active, aborting"
  exit 1
fi

# Wait briefly if webtunnel is still coming back from the last usque restart
for i in 1 2 3 4 5; do
  st=$(systemctl --user is-active ga-webtunnel.service || true)
  if [ "$st" = "active" ]; then
    break
  fi
  echo "waiting webtunnel ($st) $i"
  sleep 3
done

export HTTP_PROXY="http://127.0.0.1:18080"
export HTTPS_PROXY="http://127.0.0.1:18080"
export CHECKIN_PROXY="http://127.0.0.1:18080"
export CHECKIN_IP_ROTATE_CMD="$REPO/rotate_warp_ip.sh"

# HARD GATE: refuse to start against a dead proxy.
ip=""
for i in $(seq 1 12); do
  ip=$(curl -s --max-time 12 -x http://127.0.0.1:18080 https://api.ipify.org || true)
  [ -n "$ip" ] && break
  echo "proxy not ready (try $i)"
  sleep 8
done
if [ -z "$ip" ]; then
  echo "ABORT: proxy unreachable"
  exit 1
fi

if ! xdpyinfo -display :200 >/dev/null 2>&1; then
  Xvfb :200 -screen 0 1920x1080x24 -nolisten tcp -ac >/dev/null 2>&1 &
  sleep 2
fi

echo "[$(date '+%F %T')] launching checkin.py exit_ip=${ip} rotate=$CHECKIN_IP_ROTATE_CMD"

DISPLAY=:200 python3 -u checkin.py
