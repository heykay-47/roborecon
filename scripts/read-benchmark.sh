#!/usr/bin/env bash
set -euo pipefail

cleanup() {
  docker compose down --remove-orphans
}
trap cleanup EXIT

docker compose build api
docker compose run --rm api-test env -u DATABASE_URL python -m pytest -q -s tests/read_benchmark.py
