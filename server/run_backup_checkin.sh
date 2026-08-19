#!/bin/bash
# Server backup check-in runner: human-like random delay + WARP IP rotation + Xvfb + proxy
set -u
REPO=/home/shenhao/anyrouter-check-in
cd "$REPO"

# Needed so `systemctl --user` works under cron (no login session).
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

# Route through local usque/WARP proxy: this host cannot reach agentrouter.org /
# anyrouter.top directly (GFW resets TLS). httpx reads HTTPS_PROXY; Playwright reads CHECKIN_PROXY.
export HTTP_PROXY="http://127.0.0.1:18080"
export HTTPS_PROXY="http://127.0.0.1:18080"
export CHECKIN_PROXY="http://127.0.0.1:18080"

# Mid-run exit-IP rotation: checkin.py runs this at each WAF cooldown to start the next
# batch of accounts from a fresh Cloudflare/WARP IP, resetting Aliyun WAF per-IP penalties.
export CHECKIN_IP_ROTATE_CMD="$REPO/rotate_warp_ip.sh"

# Keep the cron log bounded: when it exceeds 5MB keep only the last 1MB.
LOG="$HOME/logs/anyrouter_backup.log"
if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt 5242880 ]; then
  tail -c 1048576 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
  echo "[$(date '+%F %T')] log truncated to last 1MB"
fi

# Human-like jitter: sleep 0-30 min before running
DELAY=$(( RANDOM % 1800 ))
echo "[$(date '+%F %T')] backup check-in: sleeping ${DELAY}s for human-like timing"
sleep "$DELAY"

# Rotate WARP exit IP before each run: Aliyun WAF penalties are per-IP and long-lived,
# so starting every run from a fresh Cloudflare egress IP resets any prior penalty.
echo "[$(date '+%F %T')] rotating WARP exit IP (usque restart)"
systemctl --user restart usque.service

# HARD GATE: never run checkin.py against a dead proxy (a broken tunnel would burn the
# whole run in Page.goto timeouts). Wait up to ~5 min; kick usque again every ~100s.
# Campus UDP/QUIC to Cloudflare WARP is occasionally filtered (esp. evening peak) and
# usually recovers within minutes; if not, skip and let the next cron slot retry.
ready=""
for i in $(seq 1 30); do
  sleep 10
  ip=$(curl -s --max-time 12 -x http://127.0.0.1:18080 https://api.ipify.org || true)
  if [ -n "$ip" ]; then
    ready="$ip"
    break
  fi
  if [ $((i % 10)) -eq 0 ]; then
    echo "[$(date '+%F %T')] proxy still down after ${i}0s, restarting usque again"
    systemctl --user restart usque.service
  fi
done
if [ -z "$ready" ]; then
  echo "[$(date '+%F %T')] ABORT: WARP proxy unreachable after 5 min; skipping this run (next cron slot retries)"
  exit 1
fi
echo "[$(date '+%F %T')] WARP proxy ready, exit IP: $ready"

# Ensure Xvfb :200 is up (needed by Playwright headless=False for WAF cookies)
if ! xdpyinfo -display :200 >/dev/null 2>&1; then
  Xvfb :200 -screen 0 1920x1080x24 -nolisten tcp -ac >/dev/null 2>&1 &
  sleep 2
fi

DISPLAY=:200 python3 checkin.py
