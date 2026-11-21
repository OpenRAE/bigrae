#!/bin/bash
# Write a CTF event's team and individual leaderboards to data.json for the display page.
#
# Usage: KUBE_CONTEXT=<context> EVENT_ID=<event uuid> OUT=<dir>/data.json [INTERVAL=60] refresh.sh
#
# The script runs a read-only scoring query in a ready portal-web pod every INTERVAL seconds.
# It publishes only rank, name, team, solves, score and member count, never emails or IDs.
# The portal's public scoreboard API returns team rankings only in team mode and sends no
# CORS headers, so a browser page cannot read it directly.
set -uo pipefail
: "${KUBE_CONTEXT:?set KUBE_CONTEXT to the tenant cluster context}"
: "${EVENT_ID:?set EVENT_ID to the CTF event UUID}"
: "${OUT:?set OUT to the data.json path next to index.html}"
INTERVAL=${INTERVAL:-60}
NAMESPACE=${NAMESPACE:-shifter-platform}

query() {
  local pod
  pod=$(kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" get pods --no-headers \
        | awk '/^portal-web/ {split($2, r, "/"); if (r[1] == r[2]) {print $1; exit}}')
  [ -n "$pod" ] || return 1
  # The portal entrypoint hydrates secrets into PID 1's environment; load them before Django setup.
  kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" exec -i "$pod" -c portal -- \
    env EVENT_ID="$EVENT_ID" sh -c 'cd /app && python -' <<'PY'
import os, sys, json
for kv in open("/proc/1/environ", "rb").read().split(b"\0"):
    if b"=" in kv:
        k, v = kv.decode(errors="replace").split("=", 1)
        os.environ.setdefault(k, v)
sys.path.insert(0, "/app")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from django.utils import timezone
from ctf.services.scoring import get_scoreboard, get_team_scoreboard
ev = os.environ["EVENT_ID"]
teams = [{"rank": r["rank"], "name": r["name"], "score": r["score"], "solves": r["solve_count"],
          "members": r.get("member_count")} for r in get_team_scoreboard(ev)]
people = [{"rank": r["rank"], "name": r["name"], "team": r.get("team_name"), "score": r["score"],
           "solves": r["solve_count"]} for r in get_scoreboard(ev)]
print("LBJSON" + json.dumps({"updated": timezone.now().isoformat(), "teams": teams, "individuals": people}))
PY
}

while true; do
  tmp=$(mktemp "${OUT}.XXXXXX")
  if query 2>/dev/null | sed -n 's/^LBJSON//p' > "$tmp" \
     && python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert {"teams","individuals"} <= set(d)' "$tmp"; then
    chmod 0644 "$tmp"
    mv "$tmp" "$OUT"
  else
    rm -f "$tmp"
  fi
  sleep "$INTERVAL"
done
