#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  ultimate/scripts/automation_lock.sh acquire [ttl_seconds]
  ultimate/scripts/automation_lock.sh release
  ultimate/scripts/automation_lock.sh status [ttl_seconds]

Creates a repository-local .codex_automation.lock so scheduled Codex runs do
not overlap with an active local/manual run.
USAGE
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
lock_file="${repo_root}/.codex_automation.lock"
action="${1:-}"
ttl_seconds="${2:-10800}"
now_epoch="$(date +%s)"
owner="${CODEX_AUTOMATION_OWNER:-codex-automation}"

lock_age() {
  local created_at="$1"
  echo $((now_epoch - created_at))
}

read_lock_created_at() {
  if [[ ! -f "${lock_file}" ]]; then
    echo ""
    return 0
  fi
  awk -F= '$1 == "created_at_epoch" {print $2}' "${lock_file}" | tail -n 1
}

case "${action}" in
  acquire)
    if [[ -f "${lock_file}" ]]; then
      created_at="$(read_lock_created_at)"
      if [[ -z "${created_at}" || ! "${created_at}" =~ ^[0-9]+$ ]]; then
        echo "stale_lock:missing_created_at:${lock_file}" >&2
        exit 2
      fi
      age="$(lock_age "${created_at}")"
      if (( age < ttl_seconds )); then
        echo "active_lock:${lock_file}:age_seconds=${age}:ttl_seconds=${ttl_seconds}" >&2
        exit 1
      fi
      echo "stale_lock:${lock_file}:age_seconds=${age}:ttl_seconds=${ttl_seconds}" >&2
      exit 2
    fi
    {
      echo "owner=${owner}"
      echo "created_at_epoch=${now_epoch}"
      echo "created_at_iso=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
      echo "cwd=${repo_root}"
      echo "pid=$$"
    } > "${lock_file}"
    echo "acquired:${lock_file}"
    ;;
  release)
    if [[ ! -f "${lock_file}" ]]; then
      echo "no_lock:${lock_file}"
      exit 0
    fi
    lock_owner="$(awk -F= '$1 == "owner" {print $2}' "${lock_file}" | tail -n 1)"
    if [[ "${lock_owner}" != "${owner}" ]]; then
      echo "not_owner:${lock_file}:owner=${lock_owner}:expected=${owner}" >&2
      exit 3
    fi
    rm -f "${lock_file}"
    echo "released:${lock_file}"
    ;;
  status)
    if [[ ! -f "${lock_file}" ]]; then
      echo "unlocked:${lock_file}"
      exit 0
    fi
    created_at="$(read_lock_created_at)"
    if [[ -z "${created_at}" || ! "${created_at}" =~ ^[0-9]+$ ]]; then
      echo "stale_lock:missing_created_at:${lock_file}"
      exit 2
    fi
    age="$(lock_age "${created_at}")"
    if (( age < ttl_seconds )); then
      echo "active_lock:${lock_file}:age_seconds=${age}:ttl_seconds=${ttl_seconds}"
      exit 1
    fi
    echo "stale_lock:${lock_file}:age_seconds=${age}:ttl_seconds=${ttl_seconds}"
    exit 2
    ;;
  *)
    usage >&2
    exit 64
    ;;
esac
