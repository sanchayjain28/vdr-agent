#!/usr/bin/env bash
# Docker entrypoint for vdr-agent.
# Runs Flyway migrations then starts the application.
set -euo pipefail

MIGRATIONS_DIR="/app/migrations/flyway"
JDBC_URL="jdbc:postgresql://${VDR_AGENT_DB_HOST}:${VDR_AGENT_DB_PORT:-5432}/${VDR_AGENT_DB_NAME}"

echo "[entrypoint] Running Flyway migrations..."
flyway \
  "-locations=filesystem:${MIGRATIONS_DIR}" \
  "-url=${JDBC_URL}" \
  "-user=${VDR_AGENT_DB_USER}" \
  "-password=${VDR_AGENT_DB_PASSWORD}" \
  "-schemas=vdr_agent" \
  "-baselineOnMigrate=true" \
  "-baselineVersion=0" \
  migrate

echo "[entrypoint] Migrations complete. Starting application..."
exec "$@"
