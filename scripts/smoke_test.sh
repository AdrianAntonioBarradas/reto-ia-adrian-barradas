#!/usr/bin/env bash
# Smoke-test a deployed agent against the Open Responses contract.
#
#   BASE_URL=https://host AGENT_API_KEY=... ./scripts/smoke_test.sh
#
# Checks the things a broken deploy actually breaks: health, discovery, auth in both
# directions, and one real grounded answer. Exits non-zero on the first failure so it
# can gate a release.
set -uo pipefail

BASE_URL="${BASE_URL:?set BASE_URL}"
AGENT_API_KEY="${AGENT_API_KEY:?set AGENT_API_KEY}"
fails=0

check() {
  local name="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    printf '  ok    %-42s %s\n' "$name" "$actual"
  else
    printf '  FAIL  %-42s got %s, want %s\n' "$name" "$actual" "$expected"
    fails=$((fails + 1))
  fi
}

code() { curl -s -o /dev/null -w '%{http_code}' --max-time 90 "$@"; }

echo "smoke test: $BASE_URL"

check "GET /health" 200 "$(code "$BASE_URL/health")"
check "GET /.well-known/agent-card.json" 200 "$(code "$BASE_URL/.well-known/agent-card.json")"
check "POST /v1/responses without a token" 401 \
  "$(code -X POST "$BASE_URL/v1/responses" -H 'Content-Type: application/json' -d '{"input":"hola"}')"
check "POST /v1/responses with a wrong token" 401 \
  "$(code -X POST "$BASE_URL/v1/responses" -H 'Authorization: Bearer wrong' \
      -H 'Content-Type: application/json' -d '{"input":"hola"}')"

# The card must advertise the base the platform will append /responses to.
# A2A v1.0 has no top-level `url`: interfaces live in supportedInterfaces, each with
# its own url and binding. Reading card["url"] silently returned "" after that
# migration, so this check was passing vacuously until the value changed.
card_url=$(curl -s --max-time 30 "$BASE_URL/.well-known/agent-card.json" \
  | python3 -c 'import json,sys
d = json.load(sys.stdin)
ifaces = d.get("supportedInterfaces") or []
print(ifaces[0].get("url", "") if ifaces else "")' 2>/dev/null)
check "agent card advertises /v1" "$BASE_URL/v1" "$card_url"

echo "  ...    asking a grounded question (this calls the LLM)"
body=$(curl -s --max-time 120 -X POST "$BASE_URL/v1/responses" \
  -H "Authorization: Bearer $AGENT_API_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"cv-agent","input":"¿Ha trabajado con Kubernetes en producción?"}')

status=$(printf '%s' "$body" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))' 2>/dev/null)
check "response status" completed "$status"

text=$(printf '%s' "$body" | python3 -c '
import json,sys
try:
    d=json.load(sys.stdin)
    print(d["output"][0]["content"][0]["text"])
except Exception:
    print("")' 2>/dev/null)

if printf '%s' "$text" | grep -qiE "aprend|no tiene experiencia|^no"; then
  printf '  ok    %-42s honest answer\n' "honesty check (Kubernetes)"
else
  printf '  FAIL  %-42s unexpected: %s\n' "honesty check (Kubernetes)" "${text:0:120}"
  fails=$((fails + 1))
fi
echo
echo "  answer: ${text:0:200}"
echo
if [ "$fails" -eq 0 ]; then echo "all checks passed"; else echo "$fails check(s) failed"; fi
exit "$fails"
