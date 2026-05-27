"""Official documentation stage built on top of the collector docs profiler."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import time
from typing import Any

import httpx

from project_knowledge_agent.config import Settings

_COLLECTOR_ROOT = Path(__file__).resolve().parents[2] / "collector_agent"
if str(_COLLECTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_COLLECTOR_ROOT))

from collector_agent.config import Settings as CollectorSettings  # noqa: E402
from collector_agent.contracts import CollectorRequest  # noqa: E402
from collector_agent.docs_profile import (  # noqa: E402
    DocumentationProfileBuilder,
    ProjectProfile,
    ProjectProfileCache,
)


@dataclass
class DocsStageResult:
    profile: ProjectProfile | None
    status: str
    summary: str
    citations: list[str]
    coverage: dict[str, Any]


class OfficialDocsStage:
    def __init__(
        self,
        settings: Settings,
        *,
        builder: DocumentationProfileBuilder | None = None,
    ) -> None:
        self.settings = settings
        self._docs_budget_seconds = max(float(settings.docs_stage_cap_seconds), 86400.0)
        self.builder = builder or DocumentationProfileBuilder(
            self._collector_settings(),
            cache=ProjectProfileCache(
                cache_dir=settings.docs_cache_dir,
                ttl_seconds=settings.docs_cache_ttl_seconds,
            ),
        )

    async def collect(
        self,
        target: Any,
        *,
        client: httpx.AsyncClient,
        period_days: int = 365,
    ) -> DocsStageResult:
        del period_days
        request = CollectorRequest.model_validate(
            {
                "target": {
                    "name": getattr(target, "name", "") or "",
                    "ticker": getattr(target, "ticker", None),
                    "coingecko_id": getattr(target, "coingecko_id", None),
                },
                "sources": ["coingecko", "defillama"],
                "criteria": {
                    "need_metrics": False,
                    "need_protocol": True,
                    "need_yields": False,
                    "need_competitors": False,
                },
                "strategy": "api_first_browser_second",
                "deadline_sec": self._docs_budget_seconds,
            }
        )
        manual_docs_urls = _manual_docs_urls_from_target(target)
        try:
            profile = await self.builder.build(
                request,
                client=client,
                deadline_at=time.monotonic() + self._docs_budget_seconds,
                refresh=True,
                manual_docs_urls=manual_docs_urls,
            )
        except Exception as exc:
            return DocsStageResult(
                profile=None,
                status="error",
                summary=f"Official documentation stage failed: {exc}",
                citations=[],
                coverage={"available": False, "reason": str(exc)},
            )

        citations = []
        for group in profile.official_urls.values():
            for url in group:
                if _is_primary_docs_url(url) and url not in citations:
                    citations.append(url)
        for url in profile.docs_urls_read:
            if _is_primary_docs_url(url) and url not in citations:
                citations.append(url)

        read_stats = dict(profile.read_stats or {})
        pages_read = int(read_stats.get("pages_read") or 0)
        summary = profile.what_the_project_does or (
            f"{profile.project_name} documentation was read, but a concise description was not extracted."
        )
        return DocsStageResult(
            profile=profile,
            status="ok" if citations else "partial",
            summary=summary,
            citations=citations,
            coverage={
                "available": True,
                "pages_read": pages_read,
                "project_type": profile.project_type,
                "project_subtype": profile.project_subtype,
                "browser_fallback_needed": bool(read_stats.get("browser_fallback_needed")),
                "docs_urls_read": len(profile.docs_urls_read),
            },
        )

    def _collector_settings(self) -> CollectorSettings:
        return CollectorSettings(
            service_token="",
            http_timeout_seconds=self.settings.http_timeout_seconds,
            coingecko_base_url="https://api.coingecko.com/api/v3",
            defillama_base_url="https://api.llama.fi",
            profile_cache_dir=self.settings.docs_cache_dir,
            profile_cache_ttl_seconds=self.settings.docs_cache_ttl_seconds,
            docs_max_pages=self.settings.docs_max_pages,
            docs_max_seed_pages=self.settings.docs_max_seed_pages,
            docs_stage_cap_seconds=self._docs_budget_seconds,
        )


def _is_primary_docs_url(url: str | None) -> bool:
    text = (url or "").strip().lower()
    if not text:
        return False
    blocked = (
        "/legal/",
        "/brand",
        "/blog",
        "/app",
        "/pro",
        "terms-of-use",
        "privacy-policy",
        "user-risks",
        "cookie-policy",
        "contact-us",
        ".zip",
    )
    return not any(item in text for item in blocked)


def _manual_docs_urls_from_target(target: Any) -> list[str]:
    metadata = getattr(target, "metadata", None) or {}
    values: list[str] = []
    for key in ("docs_url", "official_docs_url"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    for key in ("docs_urls", "official_docs_urls"):
        value = metadata.get(key)
        if isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str) and item.strip():
                    values.append(item.strip())
    unique: list[str] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique
