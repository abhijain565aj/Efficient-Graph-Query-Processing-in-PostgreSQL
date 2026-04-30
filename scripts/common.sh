#!/usr/bin/env bash
# Shared shell helpers for quiet, reproducible project scripts.

# psql must never open an interactive pager from a script.
export PSQL_PAGER=cat
export PAGER=cat

# VERBOSE=1 keeps live command output on terminal. Default is clean terminal + full logs.
: "${VERBOSE:=0}"
mkdir -p logs
if [[ -z "${LOG_FILE:-}" ]]; then
  script_name="$(basename "${0:-script}" .sh)"
  LOG_FILE="logs/${script_name}_$(date +%Y%m%d_%H%M%S).log"
fi
export LOG_FILE
: > "$LOG_FILE"

log_info() {
  echo "$*"
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE"
}

log_cmd_header() {
  printf '\n[%s] $' "$(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
  printf ' %q' "$@" >> "$LOG_FILE"
  printf '\n' >> "$LOG_FILE"
}

run_logged() {
  local description="$1"
  shift
  log_info "$description"
  log_cmd_header "$@"
  if [[ "$VERBOSE" == "1" ]]; then
    "$@" 2>&1 | tee -a "$LOG_FILE"
  else
    if ! "$@" >> "$LOG_FILE" 2>&1; then
      local status=$?
      echo "FAILED: $description" >&2
      echo "Full log: $LOG_FILE" >&2
      echo "Last 80 log lines:" >&2
      tail -80 "$LOG_FILE" >&2 || true
      exit "$status"
    fi
  fi
}
