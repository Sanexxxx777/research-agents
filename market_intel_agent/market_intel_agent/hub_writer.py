"""Persist Market Intel outputs into Hub analysis runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from market_intel_agent.hub_client import HubClient


class HubWriter:
    def __init__(self, hub_client: HubClient) -> None:
        self.hub_client = hub_client

    async def ensure_run(
        self,
        *,
        run_id: int | None,
        target_id: int | None,
        query: str | None,
        requested_sources: list[str],
        requested_by: int | None = None,
    ) -> int:
        if run_id:
            return run_id
        requested_sources_for_hub = [
            source for source in requested_sources if source in {"coingecko", "defillama"}
        ]
        created = await self.hub_client.create_analysis_run(
            {
                "query": query,
                "target_id": target_id,
                "requested_by": requested_by,
                "requested_sources": requested_sources_for_hub,
                "period_days": 365,
                "include_web_recon": False,
            }
        )
        created_id = created.get("id")
        if not isinstance(created_id, int):
            raise ValueError("Hub create_analysis_run did not return run id")
        return created_id

    async def write_observations(self, run_id: int, observations: list[dict[str, Any]]) -> dict[str, Any]:
        return await self.hub_client.append_observations(run_id, observations)

    async def write_artifacts(self, run_id: int, artifacts: list[dict[str, Any]]) -> dict[str, Any]:
        return await self.hub_client.append_artifacts(run_id, artifacts)

    async def write_snapshot(self, run_id: int, snapshot_payload: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "snapshot_kind": "evidence_pack",
            "payload_json": snapshot_payload,
        }
        return await self.hub_client.save_snapshot(run_id, payload)

    def build_observations(
        self,
        *,
        run_id: int,
        target_id: int | None,
        profile: str,
        source_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        now_iso = datetime.now(timezone.utc).isoformat()
        for result in source_results:
            observations.append(
                {
                    "run_id": run_id,
                    "target_id": target_id,
                    "source_name": result["source"],
                    "source_kind": "api_metrics",
                    "content_type": "metric",
                    "title": f"market_intel:{result['source']}",
                    "summary_text": result.get("summary_text") or f"Collected metrics from {result['source']}",
                    "url": result.get("citation_url"),
                    "confidence": result.get("confidence", 0.75),
                    "payload_json": {
                        "profile": profile,
                        "metrics": result.get("metrics") or {},
                        "status": result.get("status", "ok"),
                        "as_of": now_iso,
                    },
                    "metadata_json": {
                        "agent": "market_intel_agent",
                        "v": "v1",
                    },
                }
            )
        return observations

    def build_artifacts(
        self,
        *,
        run_id: int,
        source_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        artifacts: list[dict[str, Any]] = []
        for result in source_results:
            raw = result.get("raw_payload") or {}
            artifacts.append(
                {
                    "run_id": run_id,
                    "source_name": result["source"],
                    "artifact_type": "raw_payload",
                    "storage_kind": "inline_json",
                    "ref": json.dumps(raw, ensure_ascii=True)[:32_000],
                    "mime_type": "application/json",
                    "metadata_json": {
                        "agent": "market_intel_agent",
                        "v": "v1",
                        "status": result.get("status", "ok"),
                    },
                }
            )
        return artifacts
