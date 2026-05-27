#!/usr/bin/env python3
"""Run deterministic project analysis for multiple assets and save JSON outputs."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from market_intel_agent.service import MarketIntelAgent


async def _run_one(agent: MarketIntelAgent, asset: str, retries: int) -> tuple[dict | None, int]:
    attempts = max(1, retries)
    for attempt in range(1, attempts + 1):
        result = await agent.run_project_analysis(asset)
        if isinstance(result, dict) and isinstance(result.get("analysis"), dict):
            return result, attempt
        if attempt < attempts:
            await asyncio.sleep(1.0)
    return result if isinstance(result, dict) else None, attempts


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Run market_intel project analysis matrix")
    parser.add_argument(
        "--assets",
        default="AAVE,UNI,DYDX",
        help="Comma-separated asset inputs (default: AAVE,UNI,DYDX)",
    )
    parser.add_argument(
        "--out-dir",
        default="/tmp/mi_live_matrix",
        help="Output directory for per-asset JSON and summary.json",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Outer retry attempts per asset for transient provider flaps (default: 2)",
    )
    args = parser.parse_args()

    assets = [item.strip() for item in str(args.assets or "").split(",") if item.strip()]
    if not assets:
        print("No assets provided", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    agent = MarketIntelAgent()
    summary: list[dict] = []

    for asset in assets:
        started = time.time()
        result, attempt_used = await _run_one(agent, asset, retries=args.retries)
        elapsed = round(time.time() - started, 2)

        asset_json = out_dir / f"{asset.lower()}.json"
        asset_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        analysis = result.get("analysis") if isinstance(result, dict) else None
        if not isinstance(analysis, dict):
            summary.append(
                {
                    "asset": asset,
                    "ok": False,
                    "attempt_used": attempt_used,
                    "elapsed_sec": elapsed,
                    "error_payload_type": type(result).__name__,
                }
            )
            continue

        missing = analysis.get("missing_fields") or []
        summary.append(
            {
                "asset": asset,
                "ok": True,
                "attempt_used": attempt_used,
                "elapsed_sec": elapsed,
                "pipeline_status": analysis.get("pipeline_status"),
                "sector": analysis.get("sector"),
                "missing_count": len(missing),
                "missing_fields": [item.get("field") for item in missing],
                "source_cost": next(
                    (entry for entry in (analysis.get("fetch_audit") or []) if entry.get("event") == "source_cost"),
                    None,
                ),
                "json_path": str(asset_json),
            }
        )

    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"summary_path={summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))

