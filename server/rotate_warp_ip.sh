#!/bin/bash
# Rotate the local WARP/usque exit IP to reset per-IP Aliyun WAF rate-limit penalties.
# Called mid-run by checkin.py via CHECKIN_IP_ROTATE_CMD.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
old=$(curl -s --max-time 8 -x http://127.0.0.1:18080 https://api.ipify.org || true)
systemctl --user restart usque.service
# Tunnel re-establishment can take a while when campus UDP is flaky; wait up to ~2 min
# and kick the service once more midway. Always exit 0: if rotation fails we continue
# the run on whatever IP the proxy comes back with.
for i in $(seq 1 15); do
  sleep 8
  new=$(curl -s --max-time 10 -x http://127.0.0.1:18080 https://api.ipify.org || true)
  if [ -n "$new" ]; then
    echo "WARP rotated: ${old:-?} -> ${new}"
    exit 0
  fi
  if [ "$i" = "8" ]; then
    echo "WARP rotate: still down after ~64s, restarting usque again"
    systemctl --user restart usque.service
  fi
done
echo "WARP rotate: proxy not ready after ~2min (old=${old:-?}); continuing anyway"
exit 0
