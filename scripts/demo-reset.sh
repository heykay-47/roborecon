#!/usr/bin/env bash
set -euo pipefail

echo "Starting the offline RoboRecon demo (PostgreSQL, API, Web)..."
docker compose up -d postgres api web

echo "Resetting the deterministic benchmark and running acceptance..."
docker compose run --rm api-test python -m app.demo.acceptance

echo "Demo ready: http://localhost:${WEB_PORT:-3000}"
