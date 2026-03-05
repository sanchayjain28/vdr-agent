#!/usr/bin/env bash
# Flyway migration runner for vdr-agent.
# Mirrors ingestion-service/scripts/run_flyway_migration.sh pattern.
# Run from any directory — uses absolute paths derived from script location.
#
# Usage:
#   VDR_AGENT_ENV=local ./scripts/run_flyway_migration.sh   # loads .env.local
#   VDR_AGENT_DB_HOST=... ./scripts/run_flyway_migration.sh  # explicit env vars

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env.local"

load_env_file_preserving_existing() {
  local file="$1"
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" =~ ^[[:space:]]*$ ]] && continue
    local key="${line%%=*}"
    local val="${line#*=}"
    # Only set if not already defined in environment
    if [[ -z "${!key:-}" ]]; then
      export "${key}=${val}"
    fi
  done < "$file"
}

# Hydrate from .env.local when running locally without overriding explicit env vars.
if [[ "${VDR_AGENT_ENV:-}" == "local" && -f "${ENV_FILE}" ]]; then
  load_env_file_preserving_existing "${ENV_FILE}"
fi

# Require core DB settings
missing=()
for key in VDR_AGENT_DB_HOST VDR_AGENT_DB_PORT VDR_AGENT_DB_NAME VDR_AGENT_DB_USER VDR_AGENT_DB_PASSWORD; do
  if [[ -z "${!key:-}" ]]; then
    missing+=("${key}")
  fi
done

if ((${#missing[@]})); then
  echo "[flyway] Missing required env vars: ${missing[*]}" >&2
  echo "[flyway] Set them in your environment or in .env.local (with VDR_AGENT_ENV=local) and retry." >&2
  exit 1
fi

LOCATIONS="filesystem:${ROOT_DIR}/migrations/flyway"
JDBC_URL="jdbc:postgresql://${VDR_AGENT_DB_HOST}:${VDR_AGENT_DB_PORT:-5432}/${VDR_AGENT_DB_NAME}"
BASELINE_ON_MIGRATE="${FLYWAY_BASELINE_ON_MIGRATE:-true}"
BASELINE_VERSION="${FLYWAY_BASELINE_VERSION:-0}"

echo "[flyway] Running migrations from ${LOCATIONS}"
echo "[flyway] URL=${JDBC_URL}"
echo "[flyway] baselineOnMigrate=${BASELINE_ON_MIGRATE} baselineVersion=${BASELINE_VERSION}"

exec flyway \
  "-locations=${LOCATIONS}" \
  "-url=${JDBC_URL}" \
  "-user=${VDR_AGENT_DB_USER}" \
  "-password=${VDR_AGENT_DB_PASSWORD}" \
  "-schemas=vdr_agent" \
  "-baselineOnMigrate=${BASELINE_ON_MIGRATE}" \
  "-baselineVersion=${BASELINE_VERSION}" \
  migrate
