#!/usr/bin/env bash
set -euo pipefail

# Idempotent bootstrap for market_intel_agent metrics stack:
# - Detects OpenClaw MCP mode.
# - Installs required DefiLlama skills for first-pass execution.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${ROOT_DIR}/.openclaw"
STATE_FILE="${STATE_DIR}/market-intel-bootstrap.json"
if ! mkdir -p "${STATE_DIR}" 2>/dev/null; then
  STATE_DIR="/tmp/market-intel-bootstrap"
  STATE_FILE="${STATE_DIR}/market-intel-bootstrap.json"
  mkdir -p "${STATE_DIR}"
fi

OPENCLAW_BIN="${OPENCLAW_BIN:-openclaw}"
STRICT_MODE="${MARKET_INTEL_BOOTSTRAP_STRICT:-0}"
CHECK_ONLY="${1:-}"
TARGET_AGENT_ID="${MARKET_INTEL_OPENCLAW_AGENT_ID:-market-intel-agent}"
SWITCH_DEFAULT_AGENT="${MARKET_INTEL_SWITCH_DEFAULT_AGENT:-1}"
RESTORE_DEFAULT_AGENT="${MARKET_INTEL_RESTORE_DEFAULT_AGENT:-0}"

SKILLS=(
  "protocol-deep-dive"
  "market-analysis"
  "risk-assessment"
)

if command -v uv >/dev/null 2>&1; then
  UV_AVAILABLE="1"
else
  UV_AVAILABLE="0"
fi

skill_candidates() {
  case "$1" in
    protocol-deep-dive)
      echo "protocol-deep-dive defillama-openapi-skill defillama-api"
      ;;
    market-analysis)
      echo "market-analysis defillama-api market-analysis-cn"
      ;;
    risk-assessment)
      echo "risk-assessment"
      ;;
    *)
      echo "$1"
      ;;
  esac
}

resolved_openclaw=""
if [[ "${OPENCLAW_BIN}" == */* ]]; then
  if [[ -x "${OPENCLAW_BIN}" ]]; then
    resolved_openclaw="${OPENCLAW_BIN}"
  fi
elif command -v "${OPENCLAW_BIN}" >/dev/null 2>&1; then
  resolved_openclaw="$(command -v "${OPENCLAW_BIN}")"
fi

mcp_mode="bridge"
mcp_reason="openclaw_cli_not_found"
if [[ -n "${resolved_openclaw}" ]]; then
  if "${resolved_openclaw}" mcp --help 2>/dev/null | grep -qi "remote"; then
    mcp_mode="direct_remote_mcp"
    mcp_reason="openclaw_mcp_remote_supported"
  else
    mcp_mode="bridge"
    mcp_reason="openclaw_mcp_remote_not_detected"
  fi
fi

cat >"${STATE_FILE}" <<EOF_STATE
{
  "mcp_mode": "${mcp_mode}",
  "mcp_reason": "${mcp_reason}",
  "openclaw_bin": "${resolved_openclaw}",
  "target_agent_id": "${TARGET_AGENT_ID}",
  "switch_default_agent": "${SWITCH_DEFAULT_AGENT}",
  "restore_default_agent": "${RESTORE_DEFAULT_AGENT}",
  "skills_required": ["${SKILLS[0]}", "${SKILLS[1]}", "${SKILLS[2]}"]
}
EOF_STATE

echo "[market-intel] MCP mode: ${mcp_mode} (${mcp_reason})"
echo "[market-intel] State file: ${STATE_FILE}"
if [[ "${UV_AVAILABLE}" != "1" ]]; then
  echo "[market-intel] warning: 'uv' binary is not available in PATH."
  echo "[market-intel] note: some DefiLlama skills (for example defillama-api) may require uv runtime."
fi

if [[ "${CHECK_ONLY}" == "--check-only" ]]; then
  exit 0
fi

if [[ -z "${resolved_openclaw}" ]]; then
  echo "[market-intel] openclaw CLI not found; skipping skill install."
  if [[ "${STRICT_MODE}" == "1" ]]; then
    exit 1
  fi
  exit 0
fi

agent_index_by_id() {
  local list_json="$1"
  local agent_id="$2"
  printf '%s' "${list_json}" | TARGET_AGENT_ID="${agent_id}" node -e '
let d="";
process.stdin.on("data", (c) => d += c);
process.stdin.on("end", () => {
  try {
    const arr = JSON.parse(d);
    const id = String(process.env.TARGET_AGENT_ID || "").trim().toLowerCase();
    const idx = Array.isArray(arr) ? arr.findIndex((item) => String(item?.id || "").trim().toLowerCase() === id) : -1;
    process.stdout.write(String(idx));
  } catch {
    process.stdout.write("-1");
  }
});
' 2>/dev/null
}

default_agent_id() {
  local list_json="$1"
  printf '%s' "${list_json}" | node -e '
let d="";
process.stdin.on("data", (c) => d += c);
process.stdin.on("end", () => {
  try {
    const arr = JSON.parse(d);
    const found = Array.isArray(arr) ? arr.find((item) => item?.isDefault) : null;
    process.stdout.write(String(found?.id || ""));
  } catch {
    process.stdout.write("");
  }
});
' 2>/dev/null
}

switched_default_from=""
if [[ "${SWITCH_DEFAULT_AGENT}" == "1" ]]; then
  agents_json="$("${resolved_openclaw}" agents list --json 2>/dev/null || true)"
  if [[ -n "${agents_json}" ]]; then
    target_index="$(agent_index_by_id "${agents_json}" "${TARGET_AGENT_ID}")"
    current_default_id="$(default_agent_id "${agents_json}")"
    current_index="$(agent_index_by_id "${agents_json}" "${current_default_id}")"
    if [[ "${target_index}" =~ ^[0-9]+$ ]]; then
      if [[ "${current_default_id}" != "${TARGET_AGENT_ID}" ]]; then
        switched_default_from="${current_default_id}"
        if [[ "${current_index}" =~ ^[0-9]+$ ]]; then
          "${resolved_openclaw}" config set "agents.list[${current_index}].default" false --strict-json >/dev/null 2>&1 || true
        fi
        "${resolved_openclaw}" config set "agents.list[${target_index}].default" true --strict-json >/dev/null 2>&1 || true
        echo "[market-intel] switched default agent: ${current_default_id:-unknown} -> ${TARGET_AGENT_ID}"
      fi
    else
      echo "[market-intel] target agent not found in openclaw config: ${TARGET_AGENT_ID}"
    fi
  fi
fi

skills_list="$("${resolved_openclaw}" skills list 2>/dev/null || true)"
missing=()

for skill in "${SKILLS[@]}"; do
  installed_slug=""
  for candidate in $(skill_candidates "${skill}"); do
    if echo "${skills_list}" | grep -qiE "(^|[[:space:]])${candidate}($|[[:space:]])"; then
      installed_slug="${candidate}"
      break
    fi
  done
  if [[ -n "${installed_slug}" ]]; then
    echo "[market-intel] skill already installed: ${skill} (resolved: ${installed_slug})"
    continue
  fi

  installed=0
  for candidate in $(skill_candidates "${skill}"); do
    for variant in \
      "skills install" \
      "skill install" \
      "skills add"
    do
      if "${resolved_openclaw}" ${variant} "${candidate}" >/dev/null 2>&1; then
        echo "[market-intel] installed skill: ${skill} (resolved: ${candidate}) via '${variant}'"
        installed=1
        break 2
      fi
    done
  done

  if [[ "${installed}" -eq 0 ]]; then
    echo "[market-intel] failed to install skill automatically: ${skill}"
    missing+=("${skill}")
  fi
done

if [[ "${#missing[@]}" -gt 0 ]]; then
  echo "[market-intel] missing skills: ${missing[*]}"
  if [[ "${STRICT_MODE}" == "1" ]]; then
    exit 1
  fi
fi

if [[ "${RESTORE_DEFAULT_AGENT}" == "1" && -n "${switched_default_from}" ]]; then
  agents_json_after="$("${resolved_openclaw}" agents list --json 2>/dev/null || true)"
  if [[ -n "${agents_json_after}" ]]; then
    target_index_after="$(agent_index_by_id "${agents_json_after}" "${TARGET_AGENT_ID}")"
    previous_index_after="$(agent_index_by_id "${agents_json_after}" "${switched_default_from}")"
    if [[ "${target_index_after}" =~ ^[0-9]+$ && "${previous_index_after}" =~ ^[0-9]+$ ]]; then
      "${resolved_openclaw}" config set "agents.list[${target_index_after}].default" false --strict-json >/dev/null 2>&1 || true
      "${resolved_openclaw}" config set "agents.list[${previous_index_after}].default" true --strict-json >/dev/null 2>&1 || true
      echo "[market-intel] restored default agent: ${switched_default_from}"
    fi
  fi
fi

echo "[market-intel] bootstrap complete."
