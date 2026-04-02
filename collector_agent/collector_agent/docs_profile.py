"""Official documentation discovery, crawl, profiling, and caching."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import os
import re
import hashlib
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse
import xml.etree.ElementTree as ET

import httpx
from pydantic import BaseModel, ConfigDict, Field

from collector_agent.config import Settings
from collector_agent.contracts import CollectorRequest
from collector_agent.normalizer import utc_now
from collector_agent.sources import (
    CoinGeckoSource,
    DefiLlamaSource,
    _candidate_slug,
    _coingecko_official_links,
)

_DOC_KEYWORDS = (
    "docs",
    "documentation",
    "developers",
    "developer",
    "learn",
    "gitbook",
    "litepaper",
    "whitepaper",
    "handbook",
    "guide",
)
_TOKENOMICS_KEYWORDS = ("tokenomics", "token", "economics", "emissions", "supply")
_SECURITY_KEYWORDS = ("security", "risk", "risks", "bug bounty", "safety")
_AUDIT_KEYWORDS = ("audit", "audits")
_FAQ_KEYWORDS = ("faq", "questions")
_OVERVIEW_KEYWORDS = ("overview", "introduction", "getting started", "getting-started", "protocol overview")
_PRODUCT_KEYWORDS = (
    "product",
    "architecture",
    "governance",
    "markets",
    "vaults",
    "perpetual",
    "lending",
    "bridge",
    "oracle",
    "rwa",
)
_EXCLUDED_PATH_PARTS = (
    "/blog",
    "/news",
    "/press",
    "/media",
    "/careers",
    "/jobs",
    "/legal",
    "/privacy",
    "/terms",
    "/cookie",
    "/cookies",
    "/brand",
    "/contact",
    "/login",
    "/signup",
    "/discord",
    "/forum",
)
_CHAIN_NAMES = (
    "Ethereum",
    "Arbitrum",
    "Optimism",
    "Base",
    "Solana",
    "Bitcoin",
    "BNB Chain",
    "Avalanche",
    "Polygon",
    "Sui",
    "Aptos",
    "Sei",
    "Berachain",
    "ZkSync",
    "Linea",
    "Blast",
    "Mode",
    "Mantle",
    "Scroll",
    "Unichain",
)
_TYPE_PATTERNS: dict[str, tuple[tuple[str, int], ...]] = {
    "perp_dex": (
        ("perpetual", 5),
        ("perps", 5),
        ("perp", 4),
        ("open interest", 5),
        ("funding rate", 5),
        ("leverage", 3),
        ("derivatives exchange", 4),
        ("futures", 3),
    ),
    "lending": (
        ("lending", 5),
        ("borrow", 4),
        ("borrower", 3),
        ("money market", 4),
        ("collateral", 3),
        ("loan", 3),
        ("cdp", 4),
    ),
    "dex_spot": (
        ("swap", 4),
        ("spot exchange", 5),
        ("liquidity pool", 4),
        ("automated market maker", 4),
        ("amm", 3),
        ("trading pairs", 2),
        ("spot market", 4),
    ),
    "blockchain": (
        ("layer 1", 5),
        ("layer1", 4),
        ("layer 2", 5),
        ("layer2", 4),
        ("rollup", 4),
        ("blockchain", 4),
        ("network", 2),
        ("sequencer", 3),
    ),
    "rwa": (
        ("real-world asset", 5),
        ("real world asset", 5),
        ("treasury bills", 5),
        ("treasuries", 4),
        ("t-bill", 4),
        ("bond", 3),
        ("credit fund", 4),
    ),
    "bridge": (
        ("bridge", 5),
        ("cross-chain", 4),
        ("cross chain", 4),
        ("interoperability", 4),
        ("message passing", 4),
    ),
    "oracle": (
        ("oracle", 5),
        ("price feed", 4),
        ("data feed", 4),
        ("data availability", 3),
    ),
    "data_infra": (
        ("infrastructure", 3),
        ("indexing", 4),
        ("rpc", 4),
        ("developer platform", 4),
        ("data layer", 4),
    ),
    "vault_yield": (
        ("vault", 5),
        ("yield strategy", 4),
        ("auto-compound", 4),
        ("earn vault", 4),
        ("restaking", 3),
    ),
}
_ORDERBOOK_PATTERNS = ("order book", "orderbook", "clob", "central limit order book")
_AMM_PATTERNS = ("amm", "automated market maker", "liquidity pool")
_NON_CUSTODIAL_PATTERNS = ("non-custodial", "non custodial", "self-custody", "self custody")
_CUSTODIAL_PATTERNS = ("custodial", "custody by", "held by custodian")
_RISK_PATTERNS = (
    "risk",
    "risks",
    "smart contract risk",
    "liquidation",
    "counterparty",
    "bridge risk",
    "oracle risk",
    "custody risk",
)
_TOKEN_ROLE_PATTERNS = (
    "governance token",
    "staking token",
    "fee discount",
    "fee rebate",
    "utility token",
    "ve token",
)
_TOKEN_EXISTS_PATTERNS = ("token", "governance", "staking", "emissions")


class ProjectProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_name: str
    official_urls: dict[str, Any] = Field(default_factory=dict)
    docs_urls_read: list[str] = Field(default_factory=list)
    project_type: str = "unknown_other"
    project_subtype: str | None = None
    confidence: float = 0.0
    what_the_project_does: str | None = None
    business_model: str | None = None
    revenue_model: str | None = None
    key_product_entities: list[str] = Field(default_factory=list)
    supported_chains: list[str] = Field(default_factory=list)
    token_exists: bool | None = None
    token_role: str | None = None
    governance_present: bool | None = None
    security_section_present: bool = False
    audits_present: bool = False
    tokenomics_present: bool = False
    risk_factors: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    evidence_snippets: list[dict[str, str]] = Field(default_factory=list)
    classification_flags: dict[str, Any] = Field(default_factory=dict)
    read_stats: dict[str, Any] = Field(default_factory=dict)


@dataclass
class _DiscoveredLinks:
    official_urls: dict[str, list[str]]
    website_root: str | None
    discovery_notes: list[str]


@dataclass
class _FetchedPage:
    url: str
    title: str | None
    headings: list[str]
    text: str
    links: list[tuple[str, str]]
    is_html: bool
    needs_browser: bool
    content_type: str
    word_count: int


class ProjectProfileCache:
    def __init__(self, *, cache_dir: str, ttl_seconds: int) -> None:
        self.cache_dir = cache_dir
        self.ttl_seconds = ttl_seconds
        self._memory: dict[str, tuple[datetime, ProjectProfile]] = {}

    def get(self, key: str) -> tuple[ProjectProfile, datetime] | None:
        now = utc_now()
        memory_hit = self._memory.get(key)
        if memory_hit is not None:
            cached_at, profile = memory_hit
            if _is_cache_fresh(cached_at, now, self.ttl_seconds):
                return profile.model_copy(deep=True), cached_at
            self._memory.pop(key, None)

        path = self._cache_path(key)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            cached_at = datetime.fromisoformat(payload["cached_at"])
            profile = ProjectProfile.model_validate(payload["profile"])
        except (OSError, KeyError, ValueError, TypeError):
            return None
        if not _is_cache_fresh(cached_at, now, self.ttl_seconds):
            return None
        self._memory[key] = (cached_at, profile)
        return profile.model_copy(deep=True), cached_at

    def set(self, key: str, profile: ProjectProfile) -> datetime:
        cached_at = utc_now()
        self._memory[key] = (cached_at, profile.model_copy(deep=True))
        os.makedirs(self.cache_dir, exist_ok=True)
        path = self._cache_path(key)
        payload = {
            "cached_at": cached_at.isoformat(),
            "profile": profile.model_dump(mode="json"),
        }
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
        return cached_at

    def _cache_path(self, key: str) -> str:
        safe_key = re.sub(r"[^a-z0-9._-]+", "_", key.lower()).strip("_") or "profile"
        return os.path.join(self.cache_dir, f"{safe_key}.json")


class DocumentationProfileBuilder:
    def __init__(self, settings: Settings, *, cache: ProjectProfileCache | None = None) -> None:
        self.settings = settings
        self.cache = cache or ProjectProfileCache(
            cache_dir=settings.profile_cache_dir,
            ttl_seconds=settings.profile_cache_ttl_seconds,
        )
        self.coingecko_source = CoinGeckoSource(settings)
        self.defillama_source = DefiLlamaSource(settings)

    async def build(
        self,
        request: CollectorRequest,
        *,
        client: httpx.AsyncClient,
        deadline_at: float,
        refresh: bool = False,
    ) -> ProjectProfile:
        cache_key = _profile_cache_key(request)
        if not refresh:
            cached = self.cache.get(cache_key)
            if cached is not None:
                profile, cached_at = cached
                profile.read_stats = {
                    **profile.read_stats,
                    "cache_key": cache_key,
                    "cache_hit": True,
                    "cached_at": cached_at.isoformat(),
                    "ttl_seconds": self.settings.profile_cache_ttl_seconds,
                }
                return profile

        discovered = await self._discover_official_links(request, client=client, deadline_at=deadline_at)
        pages = await self._read_docs_contour(
            request,
            discovered=discovered,
            client=client,
            deadline_at=deadline_at,
        )
        profile = self._build_profile(request, discovered=discovered, pages=pages, cache_key=cache_key)
        cached_at = self.cache.set(cache_key, profile)
        profile.read_stats = {
            **profile.read_stats,
            "cache_key": cache_key,
            "cache_hit": False,
            "cached_at": cached_at.isoformat(),
            "ttl_seconds": self.settings.profile_cache_ttl_seconds,
        }
        return profile

    async def _discover_official_links(
        self,
        request: CollectorRequest,
        *,
        client: httpx.AsyncClient,
        deadline_at: float,
    ) -> _DiscoveredLinks:
        official_urls: dict[str, list[str]] = {
            "website": [],
            "docs": [],
            "tokenomics": [],
            "security": [],
            "audits": [],
            "faq": [],
            "overview": [],
            "product": [],
        }
        notes: list[str] = []
        website_root: str | None = None

        coin_id = None
        try:
            coin_id = await self.coingecko_source._resolve_coin_id(request, client=client, deadline_at=deadline_at)
        except Exception:
            coin_id = None
        if coin_id:
            cg_response = await client.get(
                f"{self.settings.coingecko_base_url}/coins/{coin_id}",
                params={
                    "localization": "false",
                    "tickers": "false",
                    "market_data": "false",
                    "community_data": "false",
                    "developer_data": "false",
                    "sparkline": "false",
                },
                timeout=self.coingecko_source._request_timeout(deadline_at),
            )
            cg_response.raise_for_status()
            payload = cg_response.json()
            links = _coingecko_official_links(payload.get("links") or {})
            website = str(links.get("website") or "").strip()
            if website:
                website_root = website_root or website
                _append_unique(official_urls["website"], website)
            notes.append(f"coingecko:{coin_id}")

        protocol = None
        try:
            slug = _candidate_slug(request.target.coingecko_id, request.target.name, request.target.ticker)
            protocol = await self.defillama_source._fetch_protocol_by_candidates(
                slug=slug,
                request=request,
                client=client,
                deadline_at=deadline_at,
            )
        except Exception:
            protocol = None
        if protocol is not None:
            website = str(protocol.get("url") or "").strip()
            if website:
                website_root = website_root or website
                _append_unique(official_urls["website"], website)
            for audit_url in protocol.get("audit_links") or []:
                _append_unique(official_urls["audits"], audit_url)
            notes.append(f"defillama:{protocol.get('slug')}")

        homepage_urls = official_urls["website"][: self.settings.docs_max_seed_pages]
        for homepage_url in homepage_urls:
            page = await self._fetch_page(homepage_url, client=client, deadline_at=deadline_at)
            if page is None:
                continue
            if _looks_like_docs_url(page.url):
                _append_unique(official_urls["docs"], page.url)
            for link_url, label in page.links:
                if not _is_http_url(link_url):
                    continue
                topic = _topic_for_link(label=label, url=link_url)
                if topic is None:
                    continue
                if not _is_allowed_official_link(link_url, homepage_url) and topic not in {
                    "docs",
                    "tokenomics",
                    "security",
                    "audits",
                    "faq",
                    "overview",
                    "product",
                }:
                    continue
                _append_unique(official_urls[topic], link_url)
                if topic == "docs" and website_root is None:
                    website_root = homepage_url

        if not official_urls["docs"] and website_root and _looks_like_docs_url(website_root):
            _append_unique(official_urls["docs"], website_root)

        return _DiscoveredLinks(
            official_urls=official_urls,
            website_root=website_root or (official_urls["website"][0] if official_urls["website"] else None),
            discovery_notes=notes,
        )

    async def _read_docs_contour(
        self,
        request: CollectorRequest,
        *,
        discovered: _DiscoveredLinks,
        client: httpx.AsyncClient,
        deadline_at: float,
    ) -> list[_FetchedPage]:
        seed_urls: list[str] = []
        for key in ("docs", "overview", "product", "tokenomics", "security", "audits", "faq"):
            for url in discovered.official_urls.get(key) or []:
                _append_unique(seed_urls, url)
        if not seed_urls and discovered.website_root:
            _append_unique(seed_urls, discovered.website_root)

        docs_like_prefixes = [_docs_prefix_for_url(url) for url in discovered.official_urls.get("docs") or []]
        blessed_hosts = {urlparse(url).netloc for url in seed_urls if urlparse(url).netloc}
        queue: deque[str] = deque(seed_urls[: self.settings.docs_max_seed_pages])
        visited: set[str] = set()
        pages: list[_FetchedPage] = []

        while queue and len(pages) < self.settings.docs_max_pages:
            current = _canonical_url(queue.popleft())
            if current in visited:
                continue
            visited.add(current)

            page = await self._fetch_page(current, client=client, deadline_at=deadline_at)
            if page is None:
                continue
            pages.append(page)

            current_is_docs_context = _page_is_docs_context(page.url, page)
            if current_is_docs_context:
                prefix = _docs_prefix_for_url(page.url)
                if prefix:
                    docs_like_prefixes.append(prefix)
                host = urlparse(page.url).netloc
                if host:
                    blessed_hosts.add(host)

            for link_url, label in page.links:
                normalized = _canonical_url(link_url)
                if normalized in visited:
                    continue
                if not _should_follow_docs_link(
                    normalized,
                    label=label,
                    current_page=page,
                    blessed_hosts=blessed_hosts,
                    docs_like_prefixes=docs_like_prefixes,
                ):
                    continue
                queue.append(normalized)

        return pages

    def _build_profile(
        self,
        request: CollectorRequest,
        *,
        discovered: _DiscoveredLinks,
        pages: list[_FetchedPage],
        cache_key: str,
    ) -> ProjectProfile:
        snippets = _collect_snippets(pages)
        scores, matched_keywords = _score_project_types(snippets)
        project_type, project_confidence = _choose_project_type(scores)
        flags = _build_classification_flags(snippets, scores)
        subtype = _choose_project_subtype(project_type, flags, snippets)
        what_it_does = _best_sentence(
            snippets,
            hints=(" is ", " enables ", " allows ", " lets ", " protocol ", " exchange ", " network "),
            fallback=self._fallback_description(request.target.name, project_type, subtype),
        )
        token_role = _best_sentence(snippets, hints=_TOKEN_ROLE_PATTERNS)
        revenue_model = _best_sentence(
            snippets,
            hints=("fees", "revenue", "funding", "spread", "performance fee", "management fee"),
            fallback=_revenue_model_fallback(project_type),
        )
        business_model = _business_model_fallback(project_type, subtype)
        risk_factors = _collect_risk_factors(snippets)
        supported_chains = _detect_supported_chains(snippets)
        key_entities = _detect_key_entities(snippets, project_type)
        evidence = _build_evidence_snippets(snippets, project_type, flags)
        official_urls = {key: value[:] for key, value in discovered.official_urls.items() if value}

        security_present = bool(official_urls.get("security")) or bool(
            _best_sentence(snippets, hints=_SECURITY_KEYWORDS)
        )
        audits_present = bool(official_urls.get("audits")) or bool(_best_sentence(snippets, hints=_AUDIT_KEYWORDS))
        tokenomics_present = bool(official_urls.get("tokenomics")) or bool(
            _best_sentence(snippets, hints=_TOKENOMICS_KEYWORDS)
        )
        governance_present = bool(_best_sentence(snippets, hints=("governance", "vote", "voting", "dao")))
        token_exists = _detect_token_exists(snippets, tokenomics_present)

        return ProjectProfile(
            project_name=request.target.name,
            official_urls=official_urls,
            docs_urls_read=[page.url for page in pages],
            project_type=project_type,
            project_subtype=subtype,
            confidence=project_confidence,
            what_the_project_does=what_it_does,
            business_model=business_model,
            revenue_model=revenue_model,
            key_product_entities=key_entities,
            supported_chains=supported_chains,
            token_exists=token_exists,
            token_role=token_role,
            governance_present=governance_present,
            security_section_present=security_present,
            audits_present=audits_present,
            tokenomics_present=tokenomics_present,
            risk_factors=risk_factors,
            keywords=matched_keywords,
            evidence_snippets=evidence,
            classification_flags=flags,
            read_stats={
                "cache_key": cache_key,
                "pages_discovered": len(pages),
                "pages_read": len(pages),
                "browser_fallback_needed": any(page.needs_browser for page in pages),
                "browser_fallback_supported": False,
                "browser_fallback_reasons": [page.url for page in pages if page.needs_browser][:8],
                "direct_fetch_strategy": "http_fetch_text_extract",
                "discovery_notes": discovered.discovery_notes,
            },
        )

    async def _fetch_page(
        self,
        url: str,
        *,
        client: httpx.AsyncClient,
        deadline_at: float,
    ) -> _FetchedPage | None:
        response = await client.get(
            url,
            follow_redirects=True,
            headers={"Accept": "text/html, text/plain, application/xml;q=0.9, */*;q=0.5"},
            timeout=self.coingecko_source._request_timeout(deadline_at),
        )
        if response.status_code >= 400:
            return None
        content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
        final_url = _canonical_url(str(response.url))
        body = response.text

        if "xml" in content_type and "sitemap" in body.lower():
            links = [(item, "") for item in _extract_sitemap_urls(body)]
            return _FetchedPage(
                url=final_url,
                title="sitemap",
                headings=[],
                text="",
                links=links,
                is_html=False,
                needs_browser=False,
                content_type=content_type,
                word_count=0,
            )

        if "html" in content_type or "<html" in body.lower():
            parsed = _HTMLTextExtractor(base_url=final_url)
            parsed.feed(body)
            text = _normalize_spaces(parsed.text())
            return _FetchedPage(
                url=final_url,
                title=_normalize_spaces(parsed.title) or None,
                headings=[_normalize_spaces(item) for item in parsed.headings if _normalize_spaces(item)],
                text=text,
                links=parsed.links,
                is_html=True,
                needs_browser=_needs_browser_fallback(body, text),
                content_type=content_type or "text/html",
                word_count=len(text.split()),
            )

        if content_type.endswith("markdown") or final_url.endswith(".md"):
            text, links = _extract_markdown_text_and_links(body, final_url)
            return _FetchedPage(
                url=final_url,
                title=None,
                headings=[],
                text=text,
                links=links,
                is_html=False,
                needs_browser=False,
                content_type=content_type or "text/markdown",
                word_count=len(text.split()),
            )

        text = _normalize_spaces(body)
        return _FetchedPage(
            url=final_url,
            title=None,
            headings=[],
            text=text,
            links=[],
            is_html=False,
            needs_browser=False,
            content_type=content_type or "text/plain",
            word_count=len(text.split()),
        )

    def _fallback_description(self, project_name: str, project_type: str, subtype: str | None) -> str:
        subtype_text = f" ({subtype})" if subtype else ""
        return f"{project_name} is classified as {project_type}{subtype_text} from official project documentation."


class _HTMLTextExtractor(HTMLParser):
    def __init__(self, *, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self._ignore_depth = 0
        self._current_href: str | None = None
        self._current_link_text: list[str] = []
        self._current_heading: str | None = None
        self._heading_text: list[str] = []
        self._text_parts: list[str] = []
        self.title = ""
        self._in_title = False
        self.headings: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        lower_tag = tag.lower()
        if lower_tag in {"script", "style", "noscript", "svg"}:
            self._ignore_depth += 1
            return
        if lower_tag == "a":
            href = attrs_dict.get("href")
            if href:
                self._current_href = urljoin(self.base_url, href)
                self._current_link_text = []
        if lower_tag in {"h1", "h2", "h3"}:
            self._current_heading = lower_tag
            self._heading_text = []
        if lower_tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        lower_tag = tag.lower()
        if lower_tag in {"script", "style", "noscript", "svg"}:
            self._ignore_depth = max(0, self._ignore_depth - 1)
            return
        if lower_tag == "a" and self._current_href:
            label = _normalize_spaces(" ".join(self._current_link_text))
            self.links.append((_canonical_url(self._current_href), label))
            self._current_href = None
            self._current_link_text = []
        if lower_tag in {"h1", "h2", "h3"} and self._current_heading:
            heading = _normalize_spaces(" ".join(self._heading_text))
            if heading:
                self.headings.append(heading)
                self._text_parts.append(heading)
            self._current_heading = None
            self._heading_text = []
        if lower_tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._ignore_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title = f"{self.title} {text}".strip()
        if self._current_href is not None:
            self._current_link_text.append(text)
        if self._current_heading is not None:
            self._heading_text.append(text)
        self._text_parts.append(text)

    def text(self) -> str:
        return " ".join(self._text_parts)


def _profile_cache_key(request: CollectorRequest) -> str:
    raw = "|".join(
        [
            (request.target.coingecko_id or "").strip().lower(),
            request.target.name.strip().lower(),
            (request.target.ticker or "").strip().lower(),
        ]
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    base = re.sub(r"[^a-z0-9]+", "-", request.target.name.strip().lower()).strip("-") or "project"
    return f"{base}-{digest}"


def _is_cache_fresh(cached_at: datetime, now: datetime, ttl_seconds: int) -> bool:
    if cached_at.tzinfo is None:
        cached_at = cached_at.replace(tzinfo=timezone.utc)
    return (now - cached_at).total_seconds() <= ttl_seconds


def _canonical_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        return url.strip()
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return urlunparse((parsed.scheme, parsed.netloc.lower(), path or "/", "", "", ""))


def _is_http_url(url: str) -> bool:
    return urlparse(url).scheme in {"http", "https"}


def _append_unique(items: list[str], value: str | None) -> None:
    text = _canonical_url(str(value or "").strip())
    if text and text not in items:
        items.append(text)


def _registered_domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    parts = [part for part in host.split(".") if part]
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def _is_allowed_official_link(candidate: str, website_url: str) -> bool:
    if not _is_http_url(candidate):
        return False
    if candidate.startswith("mailto:"):
        return False
    candidate_parsed = urlparse(candidate)
    website_parsed = urlparse(website_url)
    if candidate_parsed.netloc == website_parsed.netloc:
        return True
    return _registered_domain(candidate) == _registered_domain(website_url)


def _topic_for_link(*, label: str, url: str) -> str | None:
    haystack = f"{label} {url}".lower()
    if any(keyword in haystack for keyword in _DOC_KEYWORDS):
        return "docs"
    if any(keyword in haystack for keyword in _TOKENOMICS_KEYWORDS):
        return "tokenomics"
    if any(keyword in haystack for keyword in _AUDIT_KEYWORDS):
        return "audits"
    if any(keyword in haystack for keyword in _SECURITY_KEYWORDS):
        return "security"
    if any(keyword in haystack for keyword in _FAQ_KEYWORDS):
        return "faq"
    if any(keyword in haystack for keyword in _OVERVIEW_KEYWORDS):
        return "overview"
    if any(keyword in haystack for keyword in _PRODUCT_KEYWORDS):
        return "product"
    return None


def _looks_like_docs_url(url: str) -> bool:
    haystack = url.lower()
    return any(keyword in haystack for keyword in _DOC_KEYWORDS) or ".gitbook.io" in haystack


def _docs_prefix_for_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path or "/"
    if host.startswith("docs.") or ".gitbook.io" in host:
        return f"{parsed.scheme}://{host}"
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return f"{parsed.scheme}://{host}"
    if segments[0] in {"docs", "documentation", "developers", "learn"}:
        return f"{parsed.scheme}://{host}/{segments[0]}"
    if len(segments) > 1:
        return f"{parsed.scheme}://{host}/{'/'.join(segments[:-1])}"
    return f"{parsed.scheme}://{host}"


def _page_is_docs_context(url: str, page: _FetchedPage) -> bool:
    if _looks_like_docs_url(url):
        return True
    title_hints = " ".join([page.title or "", *page.headings]).lower()
    return any(keyword in title_hints for keyword in _DOC_KEYWORDS)


def _should_follow_docs_link(
    url: str,
    *,
    label: str,
    current_page: _FetchedPage,
    blessed_hosts: set[str],
    docs_like_prefixes: list[str],
) -> bool:
    if not _is_http_url(url):
        return False
    lower_url = url.lower()
    if any(part in lower_url for part in _EXCLUDED_PATH_PARTS):
        return False
    parsed = urlparse(url)
    if parsed.netloc not in blessed_hosts and not _looks_like_docs_url(url):
        return False
    if _topic_for_link(label=label, url=url) is not None:
        return True
    if _page_is_docs_context(current_page.url, current_page):
        if any(url.startswith(prefix) for prefix in docs_like_prefixes if prefix):
            return True
        return parsed.netloc == urlparse(current_page.url).netloc
    return False


def _needs_browser_fallback(raw_html: str, extracted_text: str) -> bool:
    if len(extracted_text.split()) >= 40:
        return False
    script_count = len(re.findall(r"<script[\s>]", raw_html, flags=re.IGNORECASE))
    return script_count >= 3


def _extract_markdown_text_and_links(body: str, base_url: str) -> tuple[str, list[tuple[str, str]]]:
    links: list[tuple[str, str]] = []
    for label, href in re.findall(r"\[([^\]]+)\]\(([^)]+)\)", body):
        links.append((_canonical_url(urljoin(base_url, href)), _normalize_spaces(label)))
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", body)
    return _normalize_spaces(text), links


def _extract_sitemap_urls(xml_text: str) -> list[str]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    urls: list[str] = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "loc" and element.text:
            _append_unique(urls, element.text)
    return urls


def _normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _collect_snippets(pages: list[_FetchedPage]) -> list[dict[str, str]]:
    snippets: list[dict[str, str]] = []
    for page in pages:
        text = " ".join([page.title or "", *page.headings, page.text])
        for sentence in _split_sentences(text):
            if len(sentence.split()) < 4:
                continue
            snippets.append({"url": page.url, "text": sentence})
    return snippets


def _split_sentences(text: str) -> list[str]:
    cleaned = _normalize_spaces(text)
    if not cleaned:
        return []
    chunks = re.split(r"(?<=[.!?])\s+|\s{2,}", cleaned)
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _score_project_types(snippets: list[dict[str, str]]) -> tuple[dict[str, int], list[str]]:
    scores = {name: 0 for name in _TYPE_PATTERNS}
    matched_keywords: list[str] = []
    for snippet in snippets:
        text = snippet["text"].lower()
        for project_type, patterns in _TYPE_PATTERNS.items():
            for phrase, weight in patterns:
                if phrase in text:
                    scores[project_type] += weight
                    if phrase not in matched_keywords:
                        matched_keywords.append(phrase)
    return scores, matched_keywords[:24]


def _choose_project_type(scores: dict[str, int]) -> tuple[str, float]:
    if not scores:
        return "unknown_other", 0.1
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_type, best_score = ordered[0]
    second_score = ordered[1][1] if len(ordered) > 1 else 0
    if best_score < 4 or best_score == second_score:
        return "unknown_other", 0.2 if best_score else 0.1
    confidence = min(0.98, 0.45 + (best_score / max(12, best_score + second_score)))
    return best_type, round(confidence, 2)


def _build_classification_flags(snippets: list[dict[str, str]], scores: dict[str, int]) -> dict[str, Any]:
    joined = " ".join(snippet["text"].lower() for snippet in snippets)
    orderbook = any(pattern in joined for pattern in _ORDERBOOK_PATTERNS)
    amm = any(pattern in joined for pattern in _AMM_PATTERNS)
    non_custodial = any(pattern in joined for pattern in _NON_CUSTODIAL_PATTERNS)
    custodial = any(pattern in joined for pattern in _CUSTODIAL_PATTERNS)
    return {
        "lending": scores.get("lending", 0) > 0,
        "dex_spot": scores.get("dex_spot", 0) > 0,
        "perp_dex": scores.get("perp_dex", 0) > 0,
        "blockchain": scores.get("blockchain", 0) > 0,
        "rwa": scores.get("rwa", 0) > 0,
        "bridge": scores.get("bridge", 0) > 0,
        "oracle": scores.get("oracle", 0) > 0,
        "data_infra": scores.get("data_infra", 0) > 0,
        "vault_yield": scores.get("vault_yield", 0) > 0,
        "derivatives": scores.get("perp_dex", 0) > 0,
        "orderbook_visible": orderbook,
        "amm_visible": amm,
        "custodial_visible": custodial,
        "non_custodial_visible": non_custodial,
    }


def _choose_project_subtype(project_type: str, flags: dict[str, Any], snippets: list[dict[str, str]]) -> str | None:
    joined = " ".join(snippet["text"].lower() for snippet in snippets)
    if project_type == "perp_dex":
        if flags.get("orderbook_visible"):
            return "orderbook_perp_dex"
        if flags.get("amm_visible"):
            return "amm_perp_dex"
    if project_type == "dex_spot":
        if flags.get("orderbook_visible"):
            return "orderbook_spot_dex"
        if flags.get("amm_visible"):
            return "amm_spot_dex"
    if project_type == "blockchain":
        if "layer 2" in joined or "layer2" in joined or "rollup" in joined:
            return "l2"
        if "layer 1" in joined or "layer1" in joined:
            return "l1"
    if project_type == "lending" and "cdp" in joined:
        return "cdp_lending"
    return None


def _best_sentence(
    snippets: list[dict[str, str]],
    *,
    hints: tuple[str, ...],
    fallback: str | None = None,
) -> str | None:
    lowered_hints = tuple(hint.lower() for hint in hints)
    for snippet in snippets:
        text = snippet["text"]
        lower = text.lower()
        if any(hint in lower for hint in lowered_hints):
            return text[:400]
    return fallback


def _collect_risk_factors(snippets: list[dict[str, str]]) -> list[str]:
    risks: list[str] = []
    for snippet in snippets:
        lower = snippet["text"].lower()
        if any(pattern in lower for pattern in _RISK_PATTERNS):
            text = snippet["text"][:240]
            if text not in risks:
                risks.append(text)
    return risks[:8]


def _detect_supported_chains(snippets: list[dict[str, str]]) -> list[str]:
    chains: list[str] = []
    joined = " ".join(snippet["text"] for snippet in snippets)
    lowered = joined.lower()
    for chain in _CHAIN_NAMES:
        if chain.lower() in lowered and chain not in chains:
            chains.append(chain)
    return chains[:16]


def _detect_key_entities(snippets: list[dict[str, str]], project_type: str) -> list[str]:
    entities: list[str] = []
    hint_map = {
        "perp_dex": ("markets", "positions", "collateral", "vault", "liquidations"),
        "lending": ("markets", "reserves", "collateral", "borrowers", "suppliers"),
        "dex_spot": ("pools", "pairs", "liquidity", "traders", "routes"),
        "blockchain": ("chain", "blocks", "sequencer", "validators", "ecosystem"),
        "rwa": ("issuer", "vault", "custodian", "assets", "redemptions"),
        "bridge": ("bridge", "messages", "liquidity", "routes", "chains"),
        "oracle": ("feeds", "oracles", "consumers", "data", "nodes"),
        "data_infra": ("clients", "integrations", "queries", "nodes", "datasets"),
        "vault_yield": ("vaults", "strategies", "depositors", "rewards", "positions"),
    }
    joined = " ".join(snippet["text"].lower() for snippet in snippets)
    for token in hint_map.get(project_type, ()):
        if token in joined and token not in entities:
            entities.append(token)
    return entities[:10]


def _build_evidence_snippets(
    snippets: list[dict[str, str]],
    project_type: str,
    flags: dict[str, Any],
) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    preferred_terms = {
        "perp_dex": ("perpetual", "open interest", "funding", "order book", "leverage"),
        "lending": ("lending", "borrow", "money market", "collateral"),
        "dex_spot": ("swap", "amm", "liquidity pool", "spot"),
        "blockchain": ("layer 1", "layer 2", "rollup", "network"),
        "rwa": ("real-world asset", "treasury", "bond", "custodian"),
        "bridge": ("bridge", "cross-chain", "message"),
        "oracle": ("oracle", "price feed", "data feed"),
        "data_infra": ("infrastructure", "rpc", "indexing"),
        "vault_yield": ("vault", "yield strategy", "auto-compound"),
    }.get(project_type, ())
    for snippet in snippets:
        lower = snippet["text"].lower()
        signal = next((term for term in preferred_terms if term in lower), None)
        if signal is None and flags.get("orderbook_visible") and "order book" in lower:
            signal = "order book"
        if signal is None and flags.get("amm_visible") and "amm" in lower:
            signal = "amm"
        if signal is None:
            continue
        evidence.append({"url": snippet["url"], "signal": signal, "snippet": snippet["text"][:280]})
        if len(evidence) >= 8:
            break
    return evidence


def _detect_token_exists(snippets: list[dict[str, str]], tokenomics_present: bool) -> bool | None:
    joined = " ".join(snippet["text"].lower() for snippet in snippets)
    if tokenomics_present:
        return True
    if any(pattern in joined for pattern in _TOKEN_EXISTS_PATTERNS):
        return True
    return None


def _business_model_fallback(project_type: str, subtype: str | None) -> str | None:
    mapping = {
        "perp_dex": "Facilitates perpetual trading markets and monetizes trading activity.",
        "lending": "Connects suppliers and borrowers in onchain credit markets.",
        "dex_spot": "Provides spot exchange liquidity and routing for token trading.",
        "blockchain": "Provides base-layer or rollup execution and settlement infrastructure.",
        "rwa": "Packages real-world assets into onchain products with issuer and custody workflows.",
        "bridge": "Moves assets or messages across chains via official bridging infrastructure.",
        "oracle": "Supplies external data and pricing infrastructure to onchain applications.",
        "data_infra": "Provides critical developer or data infrastructure used by other protocols.",
        "vault_yield": "Automates vault-based capital allocation into yield strategies.",
    }
    text = mapping.get(project_type)
    if text and subtype:
        return f"{text} Subtype: {subtype}."
    return text


def _revenue_model_fallback(project_type: str) -> str | None:
    mapping = {
        "perp_dex": "Primary revenue likely comes from trading fees, funding-related flows, and liquidation activity.",
        "lending": "Primary revenue likely comes from borrow demand, reserve spreads, and protocol fees.",
        "dex_spot": "Primary revenue likely comes from swap fees and protocol fee switches where enabled.",
        "blockchain": "Primary revenue likely comes from gas or network fees.",
        "rwa": "Primary revenue likely comes from issuance, management, servicing, or spread capture.",
        "bridge": "Primary revenue likely comes from bridge or messaging fees.",
        "oracle": "Primary revenue likely comes from data feed usage and service fees.",
        "data_infra": "Primary revenue likely comes from infrastructure usage by clients or protocols.",
        "vault_yield": "Primary revenue likely comes from management and performance fees.",
    }
    return mapping.get(project_type)
