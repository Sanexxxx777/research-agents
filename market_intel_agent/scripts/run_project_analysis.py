#!/usr/bin/env python3
"""Run deterministic project analysis through market_intel_agent."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from market_intel_agent.service import MarketIntelAgent


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Run market_intel project analysis")
    parser.add_argument("asset", help="Asset/protocol input, for example AAVE")
    args = parser.parse_args()

    agent = MarketIntelAgent()
    result = await agent.run_project_analysis(args.asset)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
