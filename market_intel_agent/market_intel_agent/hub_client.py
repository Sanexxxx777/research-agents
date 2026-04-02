"""HTTP client for Hub internal capability API."""

from __future__ import annotations

from typing import Any

import httpx

from market_intel_agent.config import HTTP_TIMEOUT_SECONDS, HUB_BASE_URL, HUB_SERVICE_TOKEN


class HubClient:
    def __init__(
        self,
        *,
        base_url: str = HUB_BASE_URL,
        service_token: str = HUB_SERVICE_TOKEN,
        timeout_seconds: float = HTTP_TIMEOUT_SECONDS,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.service_token = service_token
        self.timeout_seconds = timeout_seconds
        self._external_client = http_client

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.service_token:
            headers["X-Service-Token"] = self.service_token
        return headers

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._external_client is not None:
            resp = await self._external_client.get(
                f"{self.base_url}{path}",
                params=params,
                headers=self._headers(),
            )
        else:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.get(
                    f"{self.base_url}{path}",
                    params=params,
                    headers=self._headers(),
                )
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._external_client is not None:
            resp = await self._external_client.post(
                f"{self.base_url}{path}",
                json=payload or {},
                headers=self._headers(),
            )
        else:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.post(
                    f"{self.base_url}{path}",
                    json=payload or {},
                    headers=self._headers(),
                )
        resp.raise_for_status()
        return resp.json()

    async def search_targets(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        data = await self._get(
            "/api/v1/internal/capabilities/targets/search",
            params={"query": query, "limit": max(1, limit)},
        )
        return data.get("items", [])

    async def get_target_by_name(self, name: str) -> dict[str, Any] | None:
        data = await self._get(f"/api/v1/internal/capabilities/target/{name}")
        return data.get("item")

    async def get_market_status(self) -> dict[str, Any]:
        return await self._get("/api/v1/internal/capabilities/market/status")

    async def create_analysis_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/api/v1/internal/analysis-runs", payload)

    async def append_observations(self, run_id: int, observations: list[dict[str, Any]]) -> dict[str, Any]:
        return await self._post(
            f"/api/v1/internal/analysis-runs/{run_id}/observations",
            {"observations": observations},
        )

    async def append_artifacts(self, run_id: int, artifacts: list[dict[str, Any]]) -> dict[str, Any]:
        return await self._post(
            f"/api/v1/internal/analysis-runs/{run_id}/artifacts",
            {"artifacts": artifacts},
        )

    async def save_snapshot(self, run_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post(
            f"/api/v1/internal/analysis-runs/{run_id}/snapshot",
            payload,
        )
