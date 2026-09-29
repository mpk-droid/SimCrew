#!/usr/bin/env bash
# Run a SimCrew evaluation from CI and fail the job when the score is RED.
#
# Required environment:
#   SIMCREW_URL   Base URL of a SimCrew deployment, e.g. https://simcrew.example.com
#   REPO_URL      Git URL of the repository to evaluate
#   JOURNEY_ID    Journey UUID (GET $SIMCREW_URL/api/journeys)
#   PERSONA_IDS   Comma-separated persona UUIDs (GET $SIMCREW_URL/api/personas)
# Optional:
#   RUN_NAME      Defaults to "DX gate <commit>"
#   TIMEOUT_SECS  Give up after this many seconds (default 3600)
#   POLL_SECS     Seconds between status checks (default 30)
set -euo pipefail

: "${SIMCREW_URL:?}" "${REPO_URL:?}" "${JOURNEY_ID:?}" "${PERSONA_IDS:?}"
RUN_NAME="${RUN_NAME:-DX gate ${GITHUB_SHA:-${CI_COMMIT_SHA:-local}}}"
TIMEOUT_SECS="${TIMEOUT_SECS:-3600}"
POLL_SECS="${POLL_SECS:-30}"

payload=$(jq -n \
  --arg name "$RUN_NAME" \
  --arg repo "$REPO_URL" \
  --arg journey "$JOURNEY_ID" \
  --arg personas "$PERSONA_IDS" \
  '{name: $name, repo_url: $repo, journey_id: $journey,
    persona_environments: ($personas | split(",") | map({persona_id: .}))}')

RUN_ID=$(curl -sfX POST "$SIMCREW_URL/api/runs" \
  -H "Content-Type: application/json" -d "$payload" | jq -r .id)
echo "Started run $RUN_ID: $SIMCREW_URL/runs/$RUN_ID"

# Wait for the run to finish and for triage (dedup + spot checks) to settle.
deadline=$(( $(date +%s) + TIMEOUT_SECS ))
while :; do
  RUN=$(curl -sf "$SIMCREW_URL/api/runs/$RUN_ID" || echo '{}')
  status=$(jq -r '.status // "unknown"' <<<"$RUN")
  triage=$(jq -r '.triage.status // "pending"' <<<"$RUN")
  case "$status" in
    completed|failed) [[ "$triage" == complete ]] && break ;;
    cancelled) echo "Run was cancelled." >&2; exit 2 ;;
  esac
  if (( $(date +%s) > deadline )); then
    echo "Timed out after ${TIMEOUT_SECS}s (run=$status, triage=$triage)." >&2
    exit 2
  fi
  sleep "$POLL_SECS"
done

SCORE=$(jq -r '.score // "none"' <<<"$RUN")
echo "DX score: $SCORE - $(jq -r '.score_rationale // ""' <<<"$RUN")"
jq -r '.usage.total // empty | "Tokens: \(.input_tokens) in, \(.output_tokens) out, \(.calls) calls"' <<<"$RUN"

# Triaged findings are deduplicated across personas; fall back to raw ones if triage failed.
if [[ "$(jq -r '.triage.status' <<<"$RUN")" == complete ]]; then
  jq -r '.triage.triaged_findings[] | select(.severity != "nits")
         | "[\(.severity)] \(.title) (\(.personas | join(", ")); \(.verification_status))\n    \(.file_path // "-")\n    \(.suggestion // "")"' <<<"$RUN"
else
  curl -sf "$SIMCREW_URL/api/runs/$RUN_ID/findings" \
    | jq -r '.[] | select(.severity != "nits")
             | "[\(.severity)] \(.title)\n    \(.file_path // "-")\n    \(.suggestion // "")"'
fi

[[ "$SCORE" == RED ]] && exit 1 || exit 0
