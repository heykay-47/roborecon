#!/usr/bin/env bash
set -euo pipefail

api_url="${1:-${API_URL:-http://localhost:8000}}"
api_url="${api_url%/}"
transactions_path="/transactions?page=1&page_size=50"
if [[ -n "${BATCH_ID:-}" ]]; then
  transactions_path="/transactions?batch_id=${BATCH_ID}&page=1&page_size=50"
fi

endpoints=(
  "/batches?page=1&page_size=50"
  "/reconciliation-runs?page=1&page_size=50"
  "${transactions_path}"
  "/exceptions?page=1&page_size=50"
  "/audit-events?page=1&page_size=50"
)

for endpoint in "${endpoints[@]}"; do
  initial="$(
    curl --fail --silent --show-error --output /dev/null \
      --write-out '%{time_starttransfer}' "${api_url}${endpoint}"
  )"
  timings=()
  for _ in 1 2 3 4 5; do
    timings+=(
      "$(
        curl --fail --silent --show-error --output /dev/null \
          --write-out '%{time_starttransfer}' "${api_url}${endpoint}"
      )"
    )
  done
  median="$(printf '%s\n' "${timings[@]}" | sort -n | awk 'NR == 3 { print }')"
  slowest="$(printf '%s\n' "${timings[@]}" | sort -n | awk 'END { print }')"
  printf '%-58s initial=%ss median=%ss slowest=%ss\n' \
    "${endpoint}" "${initial}" "${median}" "${slowest}"
done
