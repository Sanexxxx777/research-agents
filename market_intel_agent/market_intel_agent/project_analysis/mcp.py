"""MCP integration selection for project analysis stack."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MCPPathDecision:
    mode: str
    reason: str
    openclaw_bin: str | None = None


def detect_mcp_path(openclaw_bin: str = "openclaw") -> MCPPathDecision:
    resolved = shutil.which(openclaw_bin)
    if not resolved:
        return MCPPathDecision(
            mode="bridge",
            reason="openclaw_cli_not_found",
            openclaw_bin=None,
        )

    try:
        proc = subprocess.run(
            [resolved, "mcp", "--help"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        combined = f"{proc.stdout}\n{proc.stderr}".lower()
        if "remote" in combined:
            return MCPPathDecision(
                mode="direct_remote_mcp",
                reason="openclaw_mcp_remote_supported",
                openclaw_bin=resolved,
            )
    except Exception:
        pass

    return MCPPathDecision(
        mode="bridge",
        reason="openclaw_mcp_remote_not_detected",
        openclaw_bin=resolved,
    )


def build_mcp_runtime_config(config: dict[str, Any]) -> dict[str, Any]:
    pa_cfg = config.get("project_analysis", {})
    mcp_cfg = pa_cfg.get("mcp", {}) if isinstance(pa_cfg, dict) else {}
    decision = detect_mcp_path(str(mcp_cfg.get("openclaw_bin") or "openclaw"))

    return {
        "mode": decision.mode,
        "reason": decision.reason,
        "openclaw_bin": decision.openclaw_bin,
        "defillama_mcp_url": mcp_cfg.get("defillama_url"),
        "coingecko_mcp_url": mcp_cfg.get("coingecko_url"),
        "bridge_capability_endpoint": mcp_cfg.get("bridge_capability_endpoint")
        or "/api/v1/internal/capabilities/project-analysis/{query}",
    }
