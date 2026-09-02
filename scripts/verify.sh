#!/usr/bin/env bash
set -euo pipefail

cleanup() {
  docker compose down --remove-orphans
}
trap cleanup EXIT

docker compose build
docker compose run --rm api-test python -m pytest -q
docker compose run --rm api-test ruff check app tests
docker compose run --rm api-test python -m app.demo.acceptance
docker build --target test -t roborecon-web-test apps/web
docker run --rm roborecon-web-test npm test -- --run
docker run --rm roborecon-web-test npm exec tsc -- -b
docker run --rm roborecon-web-test npm run lint
docker run --rm roborecon-web-test npm run build
docker compose config
