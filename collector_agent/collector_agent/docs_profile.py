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
from typing import Any, Callable
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
_GOVERNANCE_KEYWORDS = ("governance", "govern", "vote", "voting", "delegate", "delegation", "proposal", "dao")
_TREASURY_KEYWORDS = ("treasury", "reserves", "reserve", "surplus", "surplus buffer", "community fund", "ecosystem fund", "protocol-owned liquidity")
_TEAM_KEYWORDS = ("team", "founder", "founders", "co-founder", "cofounder", "advisor", "advisors", "leadership")
_PARTNER_KEYWORDS = ("partner", "partners", "partnership", "integration", "integrations", "investor", "investors", "backed by", "supporters")
_ROADMAP_KEYWORDS = ("roadmap", "upcoming", "planned", "coming soon", "next phase", "future plans", "milestones")
_SECURITY_KEYWORDS = ("security", "risk", "risks", "bug bounty", "safety")
_AUDIT_KEYWORDS = ("audit", "audits")
_FAQ_KEYWORDS = ("faq", "questions")
_OVERVIEW_KEYWORDS = ("overview", "introduction", "getting started", "getting-started", "protocol overview")
_PRODUCT_KEYWORDS = (
    "product",
    "about",
    "how it works",
    "how-it-works",
    "protocol",
    "ecosystem",
    "features",
    "architecture",
    "governance",
    "agent",
    "agents",
    "tokenization",
    "launchpad",
    "commerce",
    "depin",
    "wireless",
    "hotspot",
    "hotspots",
    "data credit",
    "data credits",
    "iot",
    "mobile",
    "markets",
    "market",
    "pool",
    "pools",
    "vaults",
    "trade",
    "trading",
    "swap",
    "swaps",
    "exchange",
    "perpetual",
    "lending",
    "bridge",
    "oracle",
    "rwa",
    "fees",
    "fee",
    "revenue",
    "buyback",
    "buy back",
    "burn",
    "team",
    "partners",
    "investors",
    "roadmap",
)
_SITE_CONTEXT_KEYWORDS = (
    "about",
    "overview",
    "how it works",
    "protocol",
    "docs",
    "documentation",
    "developers",
    "developer",
    "learn",
    "ecosystem",
    "governance",
    "tokenomics",
    "agent",
    "agents",
    "tokenization",
    "launchpad",
    "commerce",
    "depin",
    "wireless",
    "hotspot",
    "hotspots",
    "data credit",
    "data credits",
    "iot",
    "mobile",
    "security",
    "audit",
    "audits",
    "liquidity",
    "market",
    "markets",
    "pool",
    "pools",
    "trade",
    "trading",
    "swap",
    "swaps",
    "exchange",
    "borrow",
    "lend",
    "vault",
    "buyback",
    "buy back",
    "burn",
    "bridge",
    "rewards",
    "staking",
    "fees",
    "fee",
    "revenue",
    "team",
    "partners",
    "investors",
    "roadmap",
    "faq",
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
    "/dashboard",
    "/login",
    "/signup",
    "/join",
    "/referral",
    "/leaderboard",
    "/discord",
    "/forum",
    "/video-guides",
    "/media-assets",
)
_EXCLUDED_PATH_EXACT = (
    "/termsofuse",
    "/privacypolicy",
    "/brand-guide",
)
_BLOCKED_REFERENCE_HOSTS = (
    "defillama.com",
    "tokenterminal.com",
    "cointelegraph.com",
    "coindesk.com",
    "theblock.co",
    "prnewswire.com",
    "swift.com",
)
_STATIC_ASSET_SUFFIXES = (
    ".png",
    ".svg",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".css",
    ".js",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".map",
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
    "dex_aggregator": (
        ("dex aggregator", 8),
        ("swap aggregator", 8),
        ("liquidity aggregator", 7),
        ("smart order routing", 7),
        ("order routing", 5),
        ("best execution", 5),
        ("liquidity sources", 5),
        ("routes swaps", 5),
        ("routing api", 5),
        ("intent-based", 5),
        ("intent based", 5),
        ("solvers", 4),
        ("quotes", 3),
    ),
    "agent_platform": (
        ("agent network", 9),
        ("agent engine", 9),
        ("agent tokenization platform", 9),
        ("agent tokenization", 8),
        ("ai agent", 6),
        ("ai agents", 6),
        ("autonomous agent", 6),
        ("autonomous agents", 6),
        ("agent commerce protocol", 8),
        ("agentic framework", 6),
        ("agent launch", 6),
        ("launchpad enables founders to tokenize ai agents", 10),
        ("co-owned ai agents", 7),
        ("agent tokens", 5),
    ),
    "depin_wireless": (
        ("depin", 8),
        ("wireless network", 8),
        ("decentralized wireless", 8),
        ("people-powered network", 7),
        ("hotspot", 5),
        ("hotspots", 5),
        ("network coverage", 5),
        ("proof of coverage", 7),
        ("data credits", 8),
        ("data credit", 8),
        ("iot network", 6),
        ("mobile network", 6),
        ("lorawan", 6),
        ("5g", 4),
        ("cellular", 4),
    ),
    "blockchain": (
        ("layer 1", 5),
        ("layer1", 4),
        ("layer 2", 5),
        ("layer2", 4),
        ("rollup", 4),
        ("blockchain", 4),
        ("network", 2),
        ("public network", 4),
        ("mainnet", 3),
        ("testnet", 2),
        ("ledger", 3),
        ("validator", 3),
        ("validators", 3),
        ("native currency", 4),
        ("native token", 3),
        ("transaction fees", 4),
        ("smart contract transactions", 3),
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
        ("cross-chain messaging", 6),
        ("omnichain", 5),
        ("oapp", 5),
        ("interoperability protocol", 6),
    ),
    "oracle": (
        ("oracle", 5),
        ("price feed", 4),
        ("data feed", 4),
        ("data availability", 3),
    ),
    "synthetic_dollar": (
        ("synthetic dollar", 6),
        ("stablecoin", 5),
        ("usds", 5),
        ("generate usds", 5),
        ("redeem usds", 5),
        ("dai", 3),
        ("minting", 4),
        ("redeeming", 4),
        ("delta-neutral", 5),
        ("delta neutral", 5),
        ("backing assets", 4),
        ("backing asset", 4),
        ("off-exchange custody", 5),
        ("off exchange custody", 5),
        ("peg", 3),
    ),
    "data_infra": (
        ("infrastructure", 3),
        ("indexing", 4),
        ("indexing protocol", 8),
        ("subgraph", 6),
        ("subgraphs", 6),
        ("indexers", 5),
        ("query", 3),
        ("rpc", 4),
        ("developer platform", 4),
        ("data layer", 4),
        ("data availability", 6),
        ("decentralized storage", 8),
        ("data storage", 6),
        ("permanent storage", 7),
        ("cloud computing marketplace", 8),
        ("decentralized cloud", 7),
        ("compute marketplace", 6),
    ),
    "liquid_staking": (
        ("liquid staking", 9),
        ("liquid restaking", 9),
        ("lst", 5),
        ("lsts", 5),
        ("lrt", 5),
        ("lrts", 5),
        ("staked eth", 6),
        ("staked token", 6),
        ("staking pool", 5),
        ("staking rewards", 4),
        ("validator rewards", 4),
        ("restaking rewards", 5),
    ),
    "asset_management": (
        ("asset management", 7),
        ("managed vault", 6),
        ("managed vaults", 6),
        ("portfolio", 4),
        ("portfolios", 4),
        ("index token", 5),
        ("index products", 5),
        ("structured product", 5),
        ("structured products", 5),
        ("strategy vault", 5),
        ("rebalancing", 4),
        ("yield optimizer", 5),
    ),
    "nft_marketplace": (
        ("nft marketplace", 9),
        ("nft market", 7),
        ("nft trading", 7),
        ("collectibles marketplace", 7),
        ("creator royalties", 6),
        ("secondary sales", 5),
        ("listings", 4),
        ("bids", 3),
        ("floor price", 4),
        ("mint marketplace", 5),
    ),
    "gaming": (
        ("gamefi", 8),
        ("web3 game", 7),
        ("blockchain game", 7),
        ("gaming", 5),
        ("metaverse", 5),
        ("play-to-earn", 5),
        ("play to earn", 5),
        ("in-game", 4),
        ("game economy", 5),
        ("players", 3),
        ("quests", 3),
    ),
    "social": (
        ("socialfi", 8),
        ("social network", 6),
        ("social graph", 6),
        ("creator economy", 5),
        ("creator token", 5),
        ("fan token", 5),
        ("profiles", 3),
        ("followers", 3),
        ("community platform", 4),
    ),
    "prediction_market": (
        ("prediction market", 9),
        ("prediction markets", 9),
        ("outcome market", 8),
        ("outcome markets", 8),
        ("forecast market", 7),
        ("betting market", 6),
        ("odds", 4),
        ("market resolution", 5),
        ("oracle resolution", 5),
    ),
    "meme": (
        ("memecoin", 9),
        ("meme coin", 9),
        ("meme token", 8),
        ("community token", 5),
        ("community-driven token", 5),
        ("culture coin", 6),
        ("no utility", 6),
    ),
    "ai_network": (
        ("ai network", 7),
        ("artificial intelligence", 5),
        ("machine learning", 5),
        ("inference", 5),
        ("compute marketplace", 6),
        ("gpu compute", 6),
        ("model marketplace", 5),
        ("ai models", 5),
        ("subnets", 4),
        ("miners", 3),
        ("llm", 4),
    ),
    "vault_yield": (
        ("vault", 5),
        ("yield strategy", 4),
        ("auto-compound", 4),
        ("earn vault", 4),
        ("restaking", 3),
    ),
    "yield_trading": (
        ("trade yield", 8),
        ("hedge yield", 8),
        ("yield tokenization", 8),
        ("principal token", 7),
        ("yield token", 7),
        ("fixed yield", 5),
        ("yield market", 5),
        ("interest rate trading", 6),
        ("future yield", 5),
    ),
}
_ORDERBOOK_PATTERNS = ("order book", "orderbook", "clob", "central limit order book")
_AMM_PATTERNS = ("amm", "automated market maker", "liquidity pool", "stableswap", "stable swap", "curve amm")
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
    "used for governance",
    "used for voting",
    "used for staking",
    "used for fee",
    "token is used for",
    "staking token",
    "fee discount",
    "fee rebate",
    "utility token",
    "ve token",
)
_TOKEN_EXISTS_PATTERNS = ("token", "governance", "staking", "emissions")
_NOISE_SENTENCE_PATTERNS = (
    "skip to content",
    "powered by gitbook",
    "search ctrl",
    "search...",
    "privacy policy",
    "terms of use",
    "cookie policy",
    "all rights reserved",
    "join discord",
    "follow us",
    "sign in",
    "log in",
    "launch app",
    "open app",
    "connect wallet",
)
_META_DESCRIPTION_NAMES = {
    "description",
    "og:description",
    "twitter:description",
}
_META_TITLE_NAMES = {
    "og:title",
    "twitter:title",
    "title",
}
_JSON_NOISE_KEYS = {
    "navigation",
    "nav",
    "navbar",
    "sidebar",
    "footer",
    "breadcrumbs",
    "breadcrumb",
    "menu",
    "menus",
    "tabs",
    "toc",
    "tableofcontents",
    "table_of_contents",
    "links",
    "linkgroups",
}
_JSON_PREFERRED_TEXT_KEYS = {
    "title",
    "description",
    "subtitle",
    "summary",
    "tagline",
    "overview",
    "introduction",
    "intro",
    "hero",
    "headline",
}
DOCS_PROFILE_EXTRACTION_VERSION = "2026-04-24-core-identity-v15"


class ProjectProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_name: str
    official_urls: dict[str, Any] = Field(default_factory=dict)
    docs_urls_read: list[str] = Field(default_factory=list)
    project_type: str = "unknown_other"
    project_subtype: str | None = None
    product_lines: list[dict[str, Any]] = Field(default_factory=list)
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
    audit_providers: list[str] = Field(default_factory=list)
    audit_highlights: list[str] = Field(default_factory=list)
    security_highlights: list[str] = Field(default_factory=list)
    tokenomics_present: bool = False
    token_utility_points: list[str] = Field(default_factory=list)
    value_capture_points: list[str] = Field(default_factory=list)
    tokenomics_points: list[str] = Field(default_factory=list)
    token_distribution_points: list[str] = Field(default_factory=list)
    revenue_model_points: list[str] = Field(default_factory=list)
    governance_points: list[str] = Field(default_factory=list)
    treasury_points: list[str] = Field(default_factory=list)
    vesting_points: list[str] = Field(default_factory=list)
    treasury_control_points: list[str] = Field(default_factory=list)
    fee_recipient_points: list[str] = Field(default_factory=list)
    product_token_link_points: list[str] = Field(default_factory=list)
    team_points: list[str] = Field(default_factory=list)
    investor_partner_points: list[str] = Field(default_factory=list)
    roadmap_points: list[str] = Field(default_factory=list)
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
        manual_docs_urls: list[str] | None = None,
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

        discovered = await self._discover_official_links(
            request,
            client=client,
            deadline_at=deadline_at,
            manual_docs_urls=manual_docs_urls,
        )
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
        manual_docs_urls: list[str] | None = None,
    ) -> _DiscoveredLinks:
        official_urls: dict[str, list[str]] = {
            "website": [],
            "docs": [],
            "tokenomics": [],
            "governance": [],
            "treasury": [],
            "team": [],
            "partners": [],
            "roadmap": [],
            "security": [],
            "audits": [],
            "faq": [],
            "overview": [],
            "product": [],
        }
        notes: list[str] = []
        website_root: str | None = None
        normalized_manual_docs_urls = [
            _canonical_url(url)
            for url in (manual_docs_urls or [])
            if _is_http_url(url)
        ]
        for url in normalized_manual_docs_urls:
            _append_unique(official_urls["docs"], url)
            lower_url = url.lower()
            if any(keyword in lower_url for keyword in _TOKENOMICS_KEYWORDS):
                _append_unique(official_urls["tokenomics"], url)
            if any(keyword in lower_url for keyword in _GOVERNANCE_KEYWORDS):
                _append_unique(official_urls["governance"], url)
            if any(keyword in lower_url for keyword in _TREASURY_KEYWORDS):
                _append_unique(official_urls["treasury"], url)
            if any(keyword in lower_url for keyword in _TEAM_KEYWORDS):
                _append_unique(official_urls["team"], url)
            if any(keyword in lower_url for keyword in _PARTNER_KEYWORDS):
                _append_unique(official_urls["partners"], url)
            if any(keyword in lower_url for keyword in _ROADMAP_KEYWORDS):
                _append_unique(official_urls["roadmap"], url)
            if any(keyword in lower_url for keyword in _SECURITY_KEYWORDS):
                _append_unique(official_urls["security"], url)
            if any(keyword in lower_url for keyword in _FAQ_KEYWORDS):
                _append_unique(official_urls["faq"], url)
            if any(keyword in lower_url for keyword in _OVERVIEW_KEYWORDS):
                _append_unique(official_urls["overview"], url)
            if any(keyword in lower_url for keyword in _PRODUCT_KEYWORDS):
                _append_unique(official_urls["product"], url)
        if normalized_manual_docs_urls:
            notes.append(f"manual_docs:{len(normalized_manual_docs_urls)}")

        coin_id = None
        try:
            coin_id = await self.coingecko_source._resolve_coin_id(request, client=client, deadline_at=deadline_at)
        except Exception:
            coin_id = None
        if coin_id:
            try:
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
                if website and _is_allowed_website_root(website):
                    website_root = website_root or website
                    _append_unique(official_urls["website"], website)
                notes.append(f"coingecko:{coin_id}")
            except Exception as exc:
                notes.append(f"coingecko_error:{type(exc).__name__}")

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
            if website and _is_allowed_website_root(website):
                website_root = website_root or website
                _append_unique(official_urls["website"], website)
            for audit_url in protocol.get("audit_links") or []:
                if _is_allowed_reference_url(audit_url, website_root or website):
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
                if not _is_allowed_reference_url(link_url, homepage_url):
                    continue
                _append_unique(official_urls[topic], link_url)
                if topic == "docs" and website_root is None:
                    website_root = homepage_url

        if not official_urls["docs"]:
            for homepage_url in homepage_urls:
                for candidate in _guessed_docs_candidates(homepage_url):
                    page = await self._fetch_page(candidate, client=client, deadline_at=deadline_at)
                    if page is None:
                        continue
                    if not _page_is_docs_context(page.url, page):
                        continue
                    _append_unique(official_urls["docs"], page.url)
                    if any(keyword in page.url.lower() for keyword in _TOKENOMICS_KEYWORDS):
                        _append_unique(official_urls["tokenomics"], page.url)
                    if any(keyword in page.url.lower() for keyword in _SECURITY_KEYWORDS):
                        _append_unique(official_urls["security"], page.url)
                    break

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
        for url in discovered.official_urls.get("website") or []:
            _append_unique(seed_urls, url)
        for key in ("docs", "overview", "product", "tokenomics", "governance", "treasury", "team", "partners", "roadmap", "security", "audits", "faq"):
            for url in discovered.official_urls.get(key) or []:
                _append_unique(seed_urls, url)
        if not seed_urls and discovered.website_root:
            _append_unique(seed_urls, discovered.website_root)

        docs_like_prefixes = [_docs_prefix_for_url(url) for url in discovered.official_urls.get("docs") or []]
        project_seed_keys = ("website", "docs", "overview", "product", "tokenomics", "governance", "treasury", "team", "partners", "roadmap", "faq")
        blessed_hosts = {
            urlparse(url).netloc
            for key in project_seed_keys
            for url in (discovered.official_urls.get(key) or [])
            if urlparse(url).netloc
        }
        website_roots = {_canonical_url(url) for url in (discovered.official_urls.get("website") or [])}
        project_root_domain = _registered_domain(discovered.website_root or "") if discovered.website_root else ""
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
                if host and _registered_domain(page.url) == project_root_domain:
                    blessed_hosts.add(host)

            for link_url, label in sorted(page.links, key=lambda item: _docs_link_priority(item[0], item[1])):
                normalized = _canonical_url(link_url)
                if normalized in visited:
                    continue
                if not _should_follow_docs_link(
                    normalized,
                    label=label,
                    current_page=page,
                    blessed_hosts=blessed_hosts,
                    docs_like_prefixes=docs_like_prefixes,
                    website_roots=website_roots,
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
        official_urls = {key: value[:] for key, value in discovered.official_urls.items() if value}
        _enrich_official_urls_from_pages(official_urls, pages)
        semantic_snippets = _trusted_semantic_snippets(snippets, official_urls=official_urls) or snippets
        docs_semantic_snippets = _docs_semantic_snippets(semantic_snippets, official_urls=official_urls)
        classification_source_snippets = docs_semantic_snippets or semantic_snippets
        classification_snippets = _classification_semantic_snippets(classification_source_snippets)
        scores, matched_keywords = _score_project_types(classification_snippets)
        scores = _refine_project_type_scores(classification_snippets, scores)
        project_type, project_confidence = _choose_project_type(scores)
        flags = _build_classification_flags(classification_snippets, scores)
        subtype = _choose_project_subtype(project_type, flags, classification_snippets)
        product_lines = _collect_product_lines(
            primary_type=project_type,
            primary_subtype=subtype,
            scores=scores,
            flags=flags,
            snippets=classification_snippets,
        )
        overview_hints = (" is ", " enables ", " allows ", " lets ", " provides ", " offers ", " protocol ", " exchange ", " network ")
        overview_exclude_terms = (
            "holders can vote",
            "holders vote",
            "vote on proposals",
            "protocol proposals",
            "governance voting",
            "decentralized autonomous organization",
            "dao is",
            "governance",
            "proposal",
            "proposals",
            "upgrades",
            "fee distribution",
        )
        what_it_does = _best_project_overview_sentence(
            classification_snippets,
            project_type=project_type,
            hints=overview_hints,
            exclude_terms=overview_exclude_terms,
            fallback=self._fallback_description(request.target.name, project_type, subtype),
        )
        token_role = _best_sentence(semantic_snippets, hints=_TOKEN_ROLE_PATTERNS)
        business_model = _business_model_fallback(project_type, subtype)
        risk_factors = _collect_risk_factors(semantic_snippets)
        supported_chains = _detect_supported_chains(classification_snippets, project_type=project_type)
        key_entities = _detect_key_entities(classification_snippets or semantic_snippets, project_type)
        evidence = _build_evidence_snippets(classification_snippets or semantic_snippets, project_type, flags)
        audit_providers = _collect_audit_providers(snippets, official_urls=official_urls)
        audit_highlights = _collect_audit_highlights(snippets)
        security_highlights = _collect_security_highlights(snippets)
        token_utility_points = _collect_token_utility_points(
            semantic_snippets,
            target_name=request.target.name,
            ticker=request.target.ticker,
        )
        value_capture_points = _collect_value_capture_points(
            semantic_snippets,
            target_name=request.target.name,
            ticker=request.target.ticker,
        )
        tokenomics_points = _collect_tokenomics_points(semantic_snippets)
        token_distribution_points = _collect_token_distribution_points(semantic_snippets)
        revenue_model_points = _collect_revenue_model_points(semantic_snippets)
        revenue_model = _best_sentence(
            semantic_snippets,
            hints=("fees", "revenue", "funding", "spread", "performance fee", "management fee"),
            fallback=_revenue_model_fallback(project_type),
        )
        if revenue_model_points:
            top_revenue_point = revenue_model_points[0]
            revenue_fallback = _revenue_model_fallback(project_type)
            if not revenue_model or (revenue_fallback and revenue_model.strip().lower() == revenue_fallback.strip().lower()):
                revenue_model = top_revenue_point
        governance_points = _collect_governance_points(
            semantic_snippets,
            target_name=request.target.name,
            ticker=request.target.ticker,
        )
        treasury_points = _collect_treasury_points(semantic_snippets)
        vesting_points = _collect_vesting_points(semantic_snippets)
        treasury_control_points = _collect_treasury_control_points(semantic_snippets)
        fee_recipient_points = _collect_fee_recipient_points(semantic_snippets)
        product_token_link_points = _collect_product_token_link_points(
            semantic_snippets,
            target_name=request.target.name,
            ticker=request.target.ticker,
        )
        team_points = _collect_team_points(semantic_snippets)
        investor_partner_points = _collect_investor_partner_points(semantic_snippets)
        roadmap_points = _collect_roadmap_points(semantic_snippets)

        security_present = bool(official_urls.get("security")) or bool(
            _best_sentence(semantic_snippets, hints=_SECURITY_KEYWORDS)
        )
        audits_present = bool(official_urls.get("audits")) or bool(_best_sentence(snippets, hints=_AUDIT_KEYWORDS))
        tokenomics_present = bool(official_urls.get("tokenomics")) or bool(
            _best_sentence(semantic_snippets, hints=_TOKENOMICS_KEYWORDS)
        )
        governance_present = bool(_best_sentence(semantic_snippets, hints=("governance", "vote", "voting", "dao")))
        token_exists = _detect_token_exists(semantic_snippets, tokenomics_present)

        return ProjectProfile(
            project_name=request.target.name,
            official_urls=official_urls,
            docs_urls_read=[page.url for page in pages],
            project_type=project_type,
            project_subtype=subtype,
            product_lines=product_lines,
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
            audit_providers=audit_providers,
            audit_highlights=audit_highlights,
            security_highlights=security_highlights,
            tokenomics_present=tokenomics_present,
            token_utility_points=token_utility_points,
            value_capture_points=value_capture_points,
            tokenomics_points=tokenomics_points,
            token_distribution_points=token_distribution_points,
            revenue_model_points=revenue_model_points,
            governance_points=governance_points,
            treasury_points=treasury_points,
            vesting_points=vesting_points,
            treasury_control_points=treasury_control_points,
            fee_recipient_points=fee_recipient_points,
            product_token_link_points=product_token_link_points,
            team_points=team_points,
            investor_partner_points=investor_partner_points,
            roadmap_points=roadmap_points,
            risk_factors=risk_factors,
            keywords=matched_keywords,
            evidence_snippets=evidence,
            classification_flags=flags,
            read_stats={
                "cache_key": cache_key,
                "extraction_version": DOCS_PROFILE_EXTRACTION_VERSION,
                "pages_discovered": len(pages),
                "pages_read": len(pages),
                "browser_fallback_needed": any(page.needs_browser for page in pages),
                "browser_fallback_supported": False,
                "browser_fallback_reasons": [page.url for page in pages if page.needs_browser][:8],
                "direct_fetch_strategy": "http_fetch_text_extract",
                "discovery_notes": discovered.discovery_notes,
                "semantic_contract": "evidence_first_compatibility_hints",
                "compatibility_hint_fields": [
                    "project_type",
                    "project_subtype",
                    "business_model",
                    "revenue_model",
                    "token_role",
                ],
            },
        )

    async def _fetch_page(
        self,
        url: str,
        *,
        client: httpx.AsyncClient,
        deadline_at: float,
    ) -> _FetchedPage | None:
        try:
            response = await client.get(
                url,
                follow_redirects=True,
                headers={"Accept": "text/html, text/plain, application/xml;q=0.9, */*;q=0.5"},
                timeout=self.coingecko_source._request_timeout(deadline_at),
            )
        except Exception:
            return None
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
        self._capture_json_depth = 0
        self._json_buffer: list[str] = []
        self._current_href: str | None = None
        self._current_link_text: list[str] = []
        self._current_heading: str | None = None
        self._heading_text: list[str] = []
        self._text_parts: list[str] = []
        self.title = ""
        self._in_title = False
        self._meta_descriptions: list[str] = []
        self.headings: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        lower_tag = tag.lower()
        if lower_tag == "script":
            script_type = (attrs_dict.get("type") or "").strip().lower()
            script_id = (attrs_dict.get("id") or "").strip().lower()
            if "ld+json" in script_type or script_id in {"__next_data__", "__nuxt_data__"}:
                self._capture_json_depth += 1
                self._json_buffer = []
                return
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
        if lower_tag == "meta":
            name = (attrs_dict.get("name") or attrs_dict.get("property") or "").strip().lower()
            content = _normalize_spaces(attrs_dict.get("content") or "")
            if name in _META_DESCRIPTION_NAMES and content:
                self._meta_descriptions.append(content)
            if name in _META_TITLE_NAMES and content and not self.title:
                self.title = content

    def handle_endtag(self, tag: str) -> None:
        lower_tag = tag.lower()
        if lower_tag == "script" and self._capture_json_depth:
            self._capture_json_depth = max(0, self._capture_json_depth - 1)
            if not self._capture_json_depth:
                self._consume_embedded_json("".join(self._json_buffer))
                self._json_buffer = []
            return
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
        if self._capture_json_depth:
            self._json_buffer.append(data)
            return
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
        return " ".join([*self._meta_descriptions, *self._text_parts])

    def _consume_embedded_json(self, raw_json: str) -> None:
        raw = (raw_json or "").strip()
        if not raw:
            return
        try:
            payload = json.loads(raw)
        except Exception:
            return
        for item in _extract_text_from_json(payload):
            cleaned = _normalize_spaces(item)
            if cleaned:
                self._text_parts.append(cleaned)


def _profile_cache_key(request: CollectorRequest) -> str:
    raw = "|".join(
        [
            DOCS_PROFILE_EXTRACTION_VERSION,
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
    candidate_host = (urlparse(candidate).hostname or "").lower()
    if candidate_host.startswith("app."):
        return False
    candidate_parsed = urlparse(candidate)
    website_parsed = urlparse(website_url)
    if candidate_parsed.netloc == website_parsed.netloc:
        return True
    return _registered_domain(candidate) == _registered_domain(website_url)


def _is_allowed_reference_url(url: str, website_url: str | None = None) -> bool:
    if not _is_http_url(url):
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    if any(host == blocked or host.endswith(f".{blocked}") for blocked in _BLOCKED_REFERENCE_HOSTS):
        return False
    if any(path.endswith(suffix) for suffix in _STATIC_ASSET_SUFFIXES):
        return False
    if any(part in path for part in _EXCLUDED_PATH_PARTS):
        return False
    if path in _EXCLUDED_PATH_EXACT:
        return False
    if website_url and not _is_allowed_official_link(url, website_url):
        docs_like = _looks_like_docs_url(url)
        github_audit = host == "github.com" and any(token in path for token in ("/audit", "/audits"))
        root_label = _registered_domain(website_url).split(".", 1)[0]
        project_named_docs = docs_like and root_label and root_label in host.replace("-", "").replace("_", "")
        if not project_named_docs and not github_audit:
            return False
    return True


def _docs_link_priority(url: str, label: str) -> int:
    parsed = urlparse(url)
    haystack = f"{label} {parsed.path}".lower()
    priority_terms = (
        "fees",
        "fee",
        "revenue",
        "tokenomics",
        "token",
        "economics",
        "burn",
        "buyback",
        "buy back",
        "trade",
        "trading",
        "swap",
        "swaps",
        "exchange",
        "liquidity",
        "pool",
        "pools",
        "governance",
        "treasury",
    )
    if any(_contains_topic_term(haystack, term) for term in priority_terms):
        return 0
    if _topic_for_link(label=label, url=url) is not None:
        return 1
    return 2


def _is_allowed_website_root(url: str) -> bool:
    if not _is_http_url(url):
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    if host.startswith("app."):
        return False
    if any(part in path for part in ("/join", "/referral", "/leaderboard")):
        return False
    if not _is_allowed_reference_url(url):
        return False
    return True


def _topic_for_link(*, label: str, url: str) -> str | None:
    parsed = urlparse(url)
    haystack = f"{label} {parsed.path}".lower()
    if _looks_like_docs_url(url):
        return "docs"
    if any(_contains_topic_term(haystack, keyword) for keyword in _DOC_KEYWORDS):
        return "docs"
    if any(_contains_topic_term(haystack, keyword) for keyword in _TOKENOMICS_KEYWORDS):
        return "tokenomics"
    if any(_contains_topic_term(haystack, keyword) for keyword in _GOVERNANCE_KEYWORDS):
        return "governance"
    if any(_contains_topic_term(haystack, keyword) for keyword in _TREASURY_KEYWORDS):
        return "treasury"
    if any(_contains_topic_term(haystack, keyword) for keyword in _TEAM_KEYWORDS):
        return "team"
    if any(_contains_topic_term(haystack, keyword) for keyword in _PARTNER_KEYWORDS):
        return "partners"
    if any(_contains_topic_term(haystack, keyword) for keyword in _ROADMAP_KEYWORDS):
        return "roadmap"
    if any(_contains_topic_term(haystack, keyword) for keyword in _AUDIT_KEYWORDS):
        return "audits"
    if any(_contains_topic_term(haystack, keyword) for keyword in _SECURITY_KEYWORDS):
        return "security"
    if any(_contains_topic_term(haystack, keyword) for keyword in _FAQ_KEYWORDS):
        return "faq"
    if any(_contains_topic_term(haystack, keyword) for keyword in _OVERVIEW_KEYWORDS):
        return "overview"
    if any(_contains_topic_term(haystack, keyword) for keyword in _PRODUCT_KEYWORDS):
        return "product"
    return None


def _contains_topic_term(haystack: str, term: str) -> bool:
    normalized = (haystack or "").lower()
    keyword = (term or "").lower().strip()
    if not keyword:
        return False
    if re.search(r"[a-z0-9]", keyword):
        return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", normalized) is not None
    return keyword in normalized


def _looks_like_docs_url(url: str) -> bool:
    haystack = url.lower()
    return any(keyword in haystack for keyword in _DOC_KEYWORDS) or ".gitbook.io" in haystack


def _is_strict_docs_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "/").lower()
    if host.startswith(("docs.", "developers.", "developer.", "dev.", "learn.")):
        return True
    if ".gitbook.io" in host:
        return True
    return path == "/docs" or path.startswith("/docs/") or path == "/documentation" or path.startswith("/documentation/") or path == "/developers" or path.startswith("/developers/") or path == "/developer" or path.startswith("/developer/") or path == "/learn" or path.startswith("/learn/")


def _guessed_docs_candidates(website_url: str) -> list[str]:
    parsed = urlparse(website_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return []
    host = parsed.netloc.lower()
    root_domain = _registered_domain(website_url)
    candidates: list[str] = []
    for subdomain in ("docs", "developers", "developer", "learn", "whitepaper"):
        subdomain_root = f"{parsed.scheme}://{subdomain}.{root_domain}"
        for path in ("", "/docs", "/overview", "/introduction", "/docs/overview", "/docs/introduction"):
            _append_unique(candidates, f"{subdomain_root}{path}")
    for path in ("/docs", "/developers", "/developer", "/learn", "/documentation"):
        _append_unique(candidates, f"{parsed.scheme}://{host}{path}")
    return candidates


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
    if any(keyword in title_hints for keyword in _DOC_KEYWORDS):
        return True
    body_hints = page.text[:1200].lower()
    return any(keyword in body_hints for keyword in ("documentation", "developers", "developer docs", "getting started"))


def _enrich_official_urls_from_pages(official_urls: dict[str, list[str]], pages: list[_FetchedPage]) -> None:
    for page in pages:
        if not _is_allowed_reference_url(page.url):
            continue
        if _page_is_docs_context(page.url, page):
            _append_unique(official_urls.setdefault("docs", []), page.url)
        topic_label = " ".join(part for part in [page.title or "", *page.headings[:3]] if part).strip()
        topic = _topic_for_link(label=topic_label, url="")
        if topic == "docs":
            topic = None
        if topic is None:
            topic = _topic_for_link(label="", url=page.url)
            if topic == "docs":
                topic = None
        if topic is not None:
            _append_unique(official_urls.setdefault(topic, []), page.url)


def _should_follow_docs_link(
    url: str,
    *,
    label: str,
    current_page: _FetchedPage,
    blessed_hosts: set[str],
    docs_like_prefixes: list[str],
    website_roots: set[str],
) -> bool:
    if not _is_http_url(url):
        return False
    if not _is_allowed_reference_url(url):
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
    if current_page.url in website_roots:
        return _is_promising_site_link(url, label=label, current_page=current_page, blessed_hosts=blessed_hosts)
    return False


def _is_promising_site_link(
    url: str,
    *,
    label: str,
    current_page: _FetchedPage,
    blessed_hosts: set[str],
) -> bool:
    parsed = urlparse(url)
    if parsed.netloc not in blessed_hosts:
        return False
    if (parsed.hostname or "").lower().startswith("app."):
        return False
    haystack = f"{label} {url}".lower()
    if any(token in haystack for token in _SITE_CONTEXT_KEYWORDS):
        return True
    current_host = urlparse(current_page.url).netloc
    if parsed.netloc != current_host:
        return False
    path = parsed.path.strip("/").lower()
    if not path:
        return False
    if len(path.split("/")) > 2:
        return False
    if any(token in path for token in _SITE_CONTEXT_KEYWORDS):
        return True
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


def _extract_text_from_json(value: Any) -> list[str]:
    results: list[str] = []

    def walk(node: Any, *, parent_key: str = "") -> None:
        if isinstance(node, dict):
            lowered_keys = {str(key).lower() for key in node.keys()}
            title_value = node.get("title")
            description_value = (
                node.get("description")
                or node.get("subtitle")
                or node.get("summary")
                or node.get("tagline")
                or node.get("overview")
                or node.get("introduction")
                or node.get("intro")
            )
            if isinstance(title_value, str) and isinstance(description_value, str):
                title = _normalize_spaces(title_value)
                description = _normalize_spaces(description_value)
                if len(title.split()) >= 1 and len(description.split()) >= 4:
                    results.append(f"{title}. {description}")
            for key, item in node.items():
                normalized_key = str(key).lower()
                if normalized_key in {"url", "image", "logo", "sameas", "@context", "@type", "identifier"}:
                    continue
                if normalized_key in _JSON_NOISE_KEYS:
                    continue
                if normalized_key in {"seo", "metadata"} and isinstance(item, dict):
                    preferred = {
                        inner_key: inner_value
                        for inner_key, inner_value in item.items()
                        if str(inner_key).lower() in (_META_DESCRIPTION_NAMES | _META_TITLE_NAMES | _JSON_PREFERRED_TEXT_KEYS)
                    }
                    if preferred:
                        walk(preferred, parent_key=normalized_key)
                    continue
                if normalized_key in {"opengraph", "twitter"} and isinstance(item, dict):
                    preferred = {
                        inner_key: inner_value
                        for inner_key, inner_value in item.items()
                        if str(inner_key).lower() in {"title", "description"}
                    }
                    if preferred:
                        walk(preferred, parent_key=normalized_key)
                    continue
                walk(item, parent_key=normalized_key)
            return
        if isinstance(node, list):
            for item in node:
                walk(item, parent_key=parent_key)
            return
        if isinstance(node, str):
            text = _normalize_spaces(node)
            lowered = text.lower()
            minimum_words = 4
            if parent_key in _JSON_PREFERRED_TEXT_KEYS:
                minimum_words = 2
            if len(text.split()) < minimum_words:
                return
            if text.startswith("http://") or text.startswith("https://"):
                return
            if any(token in lowered for token in ("privacy policy", "terms of service", "all rights reserved")):
                return
            results.append(text)

    walk(value)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in results:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:80]


def _dedupe_repeated_phrase(text: str) -> str:
    words = text.split()
    if len(words) >= 8 and len(words) % 2 == 0:
        half = len(words) // 2
        if " ".join(words[:half]).lower() == " ".join(words[half:]).lower():
            return " ".join(words[:half])
    return text


def _collect_snippets(pages: list[_FetchedPage]) -> list[dict[str, str]]:
    snippets: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for page in pages:
        text = " ".join([page.title or "", *page.headings, page.text])
        for sentence in _split_sentences(text):
            cleaned = _normalize_spaces(_dedupe_repeated_phrase(sentence))
            if len(cleaned.split()) < 4:
                continue
            if _is_noise_sentence(cleaned, url=page.url):
                continue
            key = (page.url, cleaned.lower())
            if key in seen:
                continue
            seen.add(key)
            snippets.append({"url": page.url, "text": cleaned})
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
                if _phrase_matches(text, phrase):
                    scores[project_type] += weight
                    if phrase not in matched_keywords:
                        matched_keywords.append(phrase)
    return scores, matched_keywords[:24]


def _phrase_matches(text: str, phrase: str) -> bool:
    lowered = phrase.lower()
    if len(lowered) <= 4 and re.fullmatch(r"[a-z0-9]+", lowered):
        return re.search(rf"(?<![a-z0-9]){re.escape(lowered)}(?![a-z0-9])", text) is not None
    return lowered in text


def _choose_project_type(scores: dict[str, int]) -> tuple[str, float]:
    if not scores:
        return "unknown_other", 0.1
    tie_break_priority = {
        "lending": 0,
        "dex_spot": 1,
        "dex_aggregator": 2,
        "perp_dex": 3,
        "liquid_staking": 4,
        "bridge": 5,
        "oracle": 6,
        "data_infra": 7,
        "ai_network": 8,
        "agent_platform": 9,
        "depin_wireless": 10,
        "blockchain": 11,
    }
    ordered = sorted(scores.items(), key=lambda item: (item[1], -tie_break_priority.get(item[0], 99)), reverse=True)
    best_type, best_score = ordered[0]
    second_score = ordered[1][1] if len(ordered) > 1 else 0
    if best_score < 4:
        return "unknown_other", 0.2 if best_score else 0.1
    if best_score == second_score and best_score < 10:
        return "unknown_other", 0.2
    confidence = min(0.98, 0.45 + (best_score / max(12, best_score + second_score)))
    return best_type, round(confidence, 2)


def _refine_project_type_scores(snippets: list[dict[str, str]], scores: dict[str, int]) -> dict[str, int]:
    refined = dict(scores)
    joined = " ".join(snippet["text"].lower() for snippet in snippets)

    stablecoin_markers = (
        "synthetic dollar",
        "stablecoin",
        "stability",
        "minting",
        "minted",
        "redeeming",
        "redeem",
        "peg",
        "backing asset",
        "backing assets",
        "custody",
        "delta-neutral",
        "delta neutral",
    )
    direct_perp_venue_markers = (
        "perpetual exchange",
        "perpetual trading",
        "trade perpetual",
        "users trade perpetual",
        "open interest",
        "order book",
        "traders",
        "market makers",
        "trading venue",
    )
    if refined.get("perp_dex", 0) > 0 and any(marker in joined for marker in stablecoin_markers):
        strong_perp_hits = sum(1 for marker in direct_perp_venue_markers if marker in joined)
        if strong_perp_hits < 2:
            refined["perp_dex"] = 0

    yield_trading_markers = (
        "trade and hedge yield",
        "trade yield",
        "hedge yield",
        "yield tokenization",
        "principal token",
        "yield token",
        "fixed yield",
        "future yield",
        "pt and yt",
        "standardized yield",
    )
    boros_module_markers = (
        "boros",
        "funding rate",
        "interest rate trading",
        "margin and liquidations",
    )
    if any(marker in joined for marker in yield_trading_markers):
        refined["yield_trading"] = max(refined.get("yield_trading", 0), refined.get("perp_dex", 0) + 6, refined.get("dex_spot", 0) + 6, 14)
        if any(marker in joined for marker in boros_module_markers):
            refined["perp_dex"] = max(0, refined.get("perp_dex", 0) - 10)
        refined["dex_spot"] = max(0, refined.get("dex_spot", 0) - 6)

    agent_platform_markers = (
        "agent network",
        "agent engine",
        "agent tokenization platform",
        "agent tokenization",
        "tokenize ai agents",
        "tokenize ai-native businesses",
        "ai agent",
        "ai agents",
        "autonomous agent",
        "autonomous agents",
        "agent commerce protocol",
        "agentic framework",
        "agent launch",
        "agent tokens",
        "co-owned ai agents",
    )
    strong_spot_dex_markers = (
        "decentralized exchange",
        "spot exchange",
        "automated market maker",
        "token swaps",
        "swap tokens",
        "swap any token",
        "amm pools",
    )
    if any(marker in joined for marker in agent_platform_markers):
        refined["agent_platform"] = max(refined.get("agent_platform", 0), refined.get("dex_spot", 0) + 7, refined.get("blockchain", 0) + 8, 16)
        if not any(marker in joined for marker in ("layer 1", "layer1", "layer 2", "layer2", "rollup", "mainnet", "transaction fees", "smart contract transactions")):
            refined["blockchain"] = max(0, refined.get("blockchain", 0) - 8)
        refined["ai_network"] = max(0, refined.get("ai_network", 0) - 5)
        if sum(1 for marker in strong_spot_dex_markers if marker in joined) < 2:
            refined["dex_spot"] = max(0, refined.get("dex_spot", 0) - 8)

    dex_aggregator_markers = (
        "dex aggregator",
        "swap aggregator",
        "liquidity aggregator",
        "smart order routing",
        "best execution",
        "liquidity sources",
        "routes swaps",
        "routing api",
        "intent-based",
        "intent based",
        "solvers",
    )
    if sum(1 for marker in dex_aggregator_markers if marker in joined) >= 2:
        refined["dex_aggregator"] = max(refined.get("dex_aggregator", 0), refined.get("dex_spot", 0) + 5, 14)
        refined["dex_spot"] = max(0, refined.get("dex_spot", 0) - 5)
        swap_surface_markers = (
            "ultra mode",
            "manual mode",
            "limit orders",
            "recurring orders",
            "swap fees",
            "price impact",
            "slippage",
            "token swaps",
            "swap tokens",
        )
        if sum(1 for marker in swap_surface_markers if marker in joined) >= 2:
            refined["dex_aggregator"] = max(refined.get("dex_aggregator", 0), 18)
            refined["yield_trading"] = max(0, refined.get("yield_trading", 0) - 8)
            refined["lending"] = max(0, refined.get("lending", 0) - 8)
            refined["perp_dex"] = max(0, refined.get("perp_dex", 0) - 5)
            refined["prediction_market"] = max(0, refined.get("prediction_market", 0) - 5)

    depin_wireless_markers = (
        "depin",
        "wireless network",
        "decentralized wireless",
        "people-powered network",
        "hotspot",
        "hotspots",
        "network coverage",
        "proof of coverage",
        "data credits",
        "data credit",
        "iot network",
        "mobile network",
        "lorawan",
        "5g",
    )
    if sum(1 for marker in depin_wireless_markers if marker in joined) >= 3:
        refined["depin_wireless"] = max(refined.get("depin_wireless", 0), refined.get("blockchain", 0) + 8, 18)
        refined["blockchain"] = max(0, refined.get("blockchain", 0) - 8)

    liquid_staking_markers = (
        "liquid staking",
        "liquid restaking",
        "lst",
        "lsts",
        "lrt",
        "lrts",
        "staked eth",
        "liquid staking token",
        "liquid staking tokens",
    )
    direct_liquid_staking_hits = sum(1 for marker in liquid_staking_markers if _phrase_matches(joined, marker))
    if direct_liquid_staking_hits:
        refined["liquid_staking"] = max(refined.get("liquid_staking", 0), refined.get("blockchain", 0) + 5, refined.get("vault_yield", 0) + 4, 14)
        refined["blockchain"] = max(0, refined.get("blockchain", 0) - 5)
        refined["vault_yield"] = max(0, refined.get("vault_yield", 0) - 3)
    else:
        refined["liquid_staking"] = min(refined.get("liquid_staking", 0), 3)

    ai_network_markers = (
        "ai network",
        "artificial intelligence",
        "machine learning",
        "inference",
        "ai models",
        "subnets",
        "miners",
    )
    ai_network_hits = sum(1 for marker in ai_network_markers if marker in joined)
    if ai_network_hits >= 3:
        refined["ai_network"] = max(refined.get("ai_network", 0), 18)
        if not any(marker in joined for marker in ("layer 1 blockchain", "layer1 blockchain", "layer 2 blockchain", "layer2 blockchain", "rollup")):
            refined["blockchain"] = max(0, refined.get("blockchain", 0) - 8)
        refined["liquid_staking"] = max(0, refined.get("liquid_staking", 0) - 8)
        refined["gaming"] = max(0, refined.get("gaming", 0) - 8)
        refined["nft_marketplace"] = max(0, refined.get("nft_marketplace", 0) - 8)

    asset_management_markers = (
        "asset management",
        "managed vault",
        "managed vaults",
        "portfolio",
        "portfolios",
        "index token",
        "structured product",
        "strategy vault",
        "rebalancing",
        "yield optimizer",
    )
    if sum(1 for marker in asset_management_markers if marker in joined) >= 2:
        refined["asset_management"] = max(refined.get("asset_management", 0), refined.get("vault_yield", 0) + 3, 12)
        if "borrow" not in joined and "lending" not in joined:
            refined["lending"] = max(0, refined.get("lending", 0) - 4)

    nft_markers = (
        "nft marketplace",
        "nft trading",
        "creator royalties",
        "secondary sales",
        "floor price",
        "listings",
    )
    if sum(1 for marker in nft_markers if marker in joined) >= 2:
        refined["nft_marketplace"] = max(refined.get("nft_marketplace", 0), 14)
        refined["dex_spot"] = max(0, refined.get("dex_spot", 0) - 5)

    oracle_markers = (
        "real-world data",
        "real world data",
        "data feeds",
        "price feeds",
        "oracle services",
        "chainlink connects blockchains",
        "enterprise systems",
        "public sector",
    )
    strong_interoperability_hits = 0
    for marker in (
        "interoperability protocol",
        "cross-chain messaging",
        "cross chain messaging",
        "omnichain",
        "oapp",
        "send messages across chains",
        "move messages across chains",
    ):
        if marker in joined and f"not {marker}" not in joined:
            strong_interoperability_hits += 1

    if refined.get("bridge", 0) > 0 and strong_interoperability_hits < 2 and any(marker in joined for marker in oracle_markers):
        refined["oracle"] = max(refined.get("oracle", 0), refined.get("bridge", 0) + 8, 12)
        refined["bridge"] = max(0, refined["bridge"] - 8)
    strong_oracle_hits = sum(1 for marker in oracle_markers if marker in joined)
    oracle_context_markers = (
        "external data",
        "smart contracts",
        "oracle network",
        "oracle networks",
        "payment for oracle services",
        "data feeds provide",
        "developers use chainlink data feeds",
    )
    if (strong_interoperability_hits < 2 and strong_oracle_hits >= 2) or (
        strong_interoperability_hits < 2
        and
        refined.get("oracle", 0) >= 8
        and any(marker in joined for marker in oracle_context_markers)
    ):
        refined["oracle"] = max(
            refined.get("oracle", 0),
            refined.get("liquid_staking", 0) + 12,
            refined.get("synthetic_dollar", 0) + 12,
            refined.get("dex_spot", 0) + 10,
            refined.get("lending", 0) + 10,
            22,
        )
        refined["liquid_staking"] = max(0, refined.get("liquid_staking", 0) - 18)
        refined["synthetic_dollar"] = max(0, refined.get("synthetic_dollar", 0) - 14)
        refined["dex_spot"] = max(0, refined.get("dex_spot", 0) - 14)
        refined["lending"] = max(0, refined.get("lending", 0) - 10)

    interoperability_markers = (
        "layerzero",
        "interoperability protocol",
        "interoperability infrastructure",
        "cross-chain messaging",
        "cross chain messaging",
        "omnichain",
        "oapp",
        "send messages across chains",
        "move messages across chains",
    )
    base_chain_markers = (
        "layer 1 blockchain",
        "layer 2 blockchain",
        "rollup",
        "sequencer",
        "validators produce blocks",
        "execution environment",
        "settlement layer",
    )
    if any(marker in joined and f"not {marker}" not in joined for marker in interoperability_markers):
        refined["bridge"] = max(refined.get("bridge", 0), refined.get("blockchain", 0) + 6, 12)
        if sum(1 for marker in base_chain_markers if marker in joined) < 2:
            refined["blockchain"] = 0
    if refined.get("oracle", 0) >= 18 and refined.get("bridge", 0) > 0 and strong_interoperability_hits < 2:
        refined["oracle"] = max(refined.get("oracle", 0), refined.get("bridge", 0) + 8, 24)
        refined["bridge"] = max(0, refined.get("bridge", 0) - 6)
    if strong_interoperability_hits >= 2 and refined.get("bridge", 0) > 0:
        refined["bridge"] = max(refined.get("bridge", 0), refined.get("oracle", 0) + 6, 20)
        refined["oracle"] = max(0, refined.get("oracle", 0) - 16)

    payment_network_markers = (
        "stellar network",
        "stellar blockchain",
        "public network",
        "mainnet",
        "testnet",
        "native currency",
        "native token",
        "transaction fees",
        "minimum balance",
        "base reserve",
        "ledger",
        "accounts",
        "trustlines",
        "issue assets",
        "asset tokenization",
        "send payments",
        "cross-border payments",
        "payment operation",
    )
    if sum(1 for marker in payment_network_markers if marker in joined) >= 3 and strong_interoperability_hits == 0:
        refined["blockchain"] = max(refined.get("blockchain", 0), refined.get("bridge", 0) + 8, 16)
        refined["bridge"] = 0

    l1_platform_markers = (
        "smart contracts",
        "gas fees",
        "native currency",
        "native token",
        "transaction fees",
        "mainnet",
        "testnet",
        "validator",
        "validators",
        "proof-of-stake",
        "proof of stake",
        "run a node",
        "accounts",
        "ledger",
    )
    if refined.get("blockchain", 0) > 0 and ai_network_hits < 3 and strong_interoperability_hits == 0 and sum(1 for marker in l1_platform_markers if marker in joined) >= 4:
        refined["blockchain"] = max(refined.get("blockchain", 0), 20)
        for noisy in ("agent_platform", "dex_spot", "dex_aggregator", "gaming", "nft_marketplace", "oracle", "prediction_market", "synthetic_dollar", "vault_yield"):
            refined[noisy] = max(0, refined.get(noisy, 0) - 10)

    lending_markers = (
        "lending",
        "borrowing",
        "borrowers",
        "lenders",
        "overcollateralized",
        "over-collateralized",
        "collateral",
        "loan",
        "loans",
        "borrow assets",
        "borrow against collateral",
        "lending markets",
        "permissionless market",
        "permissionless markets",
        "money market",
    )
    vault_product_markers = (
        "vault creators",
        "vault owner",
        "vault owners",
        "morpho vaults",
        "curated lending",
        "lending products",
    )
    if refined.get("vault_yield", 0) > 0 and any(marker in joined for marker in lending_markers):
        refined["lending"] = max(refined.get("lending", 0), refined.get("vault_yield", 0) + 3)
        if any(marker in joined for marker in vault_product_markers):
            refined["vault_yield"] = max(0, refined["vault_yield"] - 4)

    data_availability_markers = (
        "data availability",
        "data availability layer",
        "blobspace",
        "blockspace",
        "data roots",
        "data root",
        "retrievability",
    )
    if sum(1 for marker in data_availability_markers if marker in joined) >= 2:
        refined["data_infra"] = max(refined.get("data_infra", 0), refined.get("oracle", 0) + 6, 18)
        refined["oracle"] = max(0, refined.get("oracle", 0) - 12)

    if refined.get("lending", 0) >= 10 and strong_oracle_hits < 2:
        refined["oracle"] = max(0, refined.get("oracle", 0) - 14)
    if refined.get("dex_spot", 0) >= 10 and strong_oracle_hits < 2:
        refined["oracle"] = max(0, refined.get("oracle", 0) - 12)
    if refined.get("liquid_staking", 0) >= 10 and strong_oracle_hits < 2:
        refined["oracle"] = max(0, refined.get("oracle", 0) - 14)
    if refined.get("perp_dex", 0) >= 12 and strong_oracle_hits < 2:
        refined["oracle"] = max(0, refined.get("oracle", 0) - 10)

    dex_identity_markers = (
        "decentralized exchange",
        "automated market maker",
        "swap tokens",
        "token swaps",
        "liquidity pools",
        "liquidity pool",
        "spot trading",
    )
    if sum(1 for marker in dex_identity_markers if marker in joined) >= 2:
        refined["dex_spot"] = max(refined.get("dex_spot", 0), refined.get("lending", 0) + 6, refined.get("yield_trading", 0) + 6, refined.get("bridge", 0) + 6, 18)
        for noisy in ("lending", "yield_trading", "bridge", "oracle", "liquid_staking", "asset_management"):
            refined[noisy] = max(0, refined.get(noisy, 0) - 8)

    if direct_liquid_staking_hits:
        refined["liquid_staking"] = max(refined.get("liquid_staking", 0), refined.get("blockchain", 0) + 6, 18)
        if not any(marker in joined for marker in ("layer 1 blockchain", "layer1 blockchain", "layer 2 blockchain", "rollup")):
            refined["blockchain"] = max(0, refined.get("blockchain", 0) - 10)
    elif refined.get("blockchain", 0) >= 12:
        refined["liquid_staking"] = max(0, refined.get("liquid_staking", 0) - 10)

    if ai_network_hits >= 3:
        refined["ai_network"] = max(refined.get("ai_network", 0), refined.get("blockchain", 0) + 6, 20)
        refined["blockchain"] = max(0, refined.get("blockchain", 0) - 8)

    storage_compute_markers = (
        "decentralized storage",
        "data storage",
        "permanent storage",
        "storage provider",
        "storage providers",
        "cloud computing marketplace",
        "decentralized cloud",
        "compute marketplace",
    )
    if sum(1 for marker in storage_compute_markers if marker in joined) >= 1:
        refined["data_infra"] = max(refined.get("data_infra", 0), refined.get("blockchain", 0) + 6, 18)
        refined["blockchain"] = max(0, refined.get("blockchain", 0) - 8)
        for noisy in ("oracle", "liquid_staking", "gaming", "ai_network"):
            refined[noisy] = max(0, refined.get(noisy, 0) - 8)
    if any(marker in joined for marker in ("cloud computing marketplace", "decentralized cloud")):
        refined["data_infra"] = max(refined.get("data_infra", 0), refined.get("ai_network", 0) + 6, 20)
        refined["ai_network"] = max(0, refined.get("ai_network", 0) - 8)

    graph_indexing_markers = ("the graph network", "subgraphs", "subgraph", "indexers", "indexing protocol", "query blockchain data")
    if sum(1 for marker in graph_indexing_markers if marker in joined) >= 2:
        refined["data_infra"] = max(refined.get("data_infra", 0), refined.get("blockchain", 0) + 6, 18)
        refined["blockchain"] = max(0, refined.get("blockchain", 0) - 8)

    if refined.get("lending", 0) >= 10 and any(marker in joined for marker in lending_markers):
        refined["lending"] = max(refined.get("lending", 0), refined.get("asset_management", 0) + 4, 16)
        refined["asset_management"] = max(0, refined.get("asset_management", 0) - 6)

    agent_or_ai_score = max(refined.get("agent_platform", 0), refined.get("ai_network", 0))
    direct_lending_protocol_markers = (
        "lending protocol",
        "borrowers",
        "lenders",
        "borrow assets",
        "supply assets",
        "money market",
        "overcollateralized lending",
        "over-collateralized lending",
        "collateralized loans",
    )
    optimizer_lending_context_markers = (
        "capital be distributed across lending markets",
        "agents actively test",
        "agents have moved",
        "standardized apr",
        "defi agents",
        "autonomous agents",
    )
    if agent_or_ai_score >= 14 and refined.get("lending", 0) > 0:
        direct_lending_hits = sum(1 for marker in direct_lending_protocol_markers if marker in joined)
        optimizer_context_hits = sum(1 for marker in optimizer_lending_context_markers if marker in joined)
        if direct_lending_hits < 2 or optimizer_context_hits >= 2:
            refined["lending"] = max(0, min(refined.get("lending", 0), agent_or_ai_score - 8))

    return refined


def _build_classification_flags(snippets: list[dict[str, str]], scores: dict[str, int]) -> dict[str, Any]:
    joined = " ".join(snippet["text"].lower() for snippet in snippets)
    orderbook = any(pattern in joined for pattern in _ORDERBOOK_PATTERNS)
    amm = any(pattern in joined for pattern in _AMM_PATTERNS)
    non_custodial = any(pattern in joined for pattern in _NON_CUSTODIAL_PATTERNS)
    custodial = any(pattern in joined for pattern in _CUSTODIAL_PATTERNS)
    return {
        "lending": scores.get("lending", 0) >= 4,
        "dex_spot": scores.get("dex_spot", 0) >= 4,
        "perp_dex": scores.get("perp_dex", 0) >= 4,
        "blockchain": scores.get("blockchain", 0) >= 4,
        "rwa": scores.get("rwa", 0) >= 4,
        "agent_platform": scores.get("agent_platform", 0) >= 4,
        "depin_wireless": scores.get("depin_wireless", 0) >= 4,
        "dex_aggregator": scores.get("dex_aggregator", 0) >= 4,
        "liquid_staking": scores.get("liquid_staking", 0) >= 4,
        "asset_management": scores.get("asset_management", 0) >= 4,
        "nft_marketplace": scores.get("nft_marketplace", 0) >= 4,
        "gaming": scores.get("gaming", 0) >= 4,
        "social": scores.get("social", 0) >= 4,
        "prediction_market": scores.get("prediction_market", 0) >= 4,
        "meme": scores.get("meme", 0) >= 4,
        "ai_network": scores.get("ai_network", 0) >= 4,
        "bridge": scores.get("bridge", 0) >= 4,
        "oracle": scores.get("oracle", 0) >= 4,
        "synthetic_dollar": scores.get("synthetic_dollar", 0) >= 4,
        "data_infra": scores.get("data_infra", 0) >= 4,
        "vault_yield": scores.get("vault_yield", 0) >= 4,
        "yield_trading": scores.get("yield_trading", 0) >= 4,
        "derivatives": scores.get("perp_dex", 0) > 0,
        "orderbook_visible": orderbook,
        "amm_visible": amm,
        "custodial_visible": custodial,
        "non_custodial_visible": non_custodial,
    }


def _choose_project_subtype(project_type: str, flags: dict[str, Any], snippets: list[dict[str, str]]) -> str | None:
    joined = " ".join(snippet["text"].lower() for snippet in snippets)
    joined_urls = " ".join((snippet.get("url") or "").lower() for snippet in snippets)
    if project_type == "perp_dex":
        if flags.get("orderbook_visible"):
            return "orderbook_perp_dex"
        if flags.get("amm_visible"):
            return "amm_perp_dex"
    if project_type == "dex_spot":
        if any(marker in joined for marker in ("automated market maker", "liquidity pool", "liquidity pools", "stableswap", "stable swap", "curve amm")):
            return "amm_spot_dex"
        if any(marker in joined_urls for marker in ("/amm/", "curve-amm", "stableswap")):
            return "amm_spot_dex"
        if flags.get("amm_visible"):
            return "amm_spot_dex"
        if flags.get("orderbook_visible"):
            return "orderbook_spot_dex"
    if project_type == "blockchain":
        if any(marker in joined for marker in ("payment network", "payments", "payment applications", "cross-border payments", "send payments", "payment operation", "asset issuance", "asset tokenization", "tokenization", "issue assets", "stellar network")):
            return "payments_tokenization_l1"
        if "layer 2" in joined or "layer2" in joined or "rollup" in joined:
            return "l2"
        if "layer 1" in joined or "layer1" in joined:
            return "l1"
    if project_type == "lending" and "cdp" in joined:
        return "cdp_lending"
    return None


def _collect_product_lines(
    *,
    primary_type: str,
    primary_subtype: str | None,
    scores: dict[str, int],
    flags: dict[str, Any],
    snippets: list[dict[str, str]],
) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()

    def add_line(line_type: str, subtype: str | None, *, role: str, score: int) -> None:
        key = (line_type, subtype)
        if not line_type or line_type == "unknown_other" or key in seen:
            return
        seen.add(key)
        lines.append(
            {
                "type": line_type,
                "subtype": subtype,
                "role": role,
                "confidence": round(min(1.0, max(0.0, score / 16.0)), 2),
                "evidence_urls": _product_line_evidence_urls(line_type, snippets),
            }
        )

    add_line(primary_type, primary_subtype, role="primary", score=scores.get(primary_type, 0))

    for candidate, score in sorted(scores.items(), key=lambda item: item[1], reverse=True):
        if candidate == primary_type or score < 6:
            continue
        if _skip_secondary_product_line(primary_type, candidate):
            continue
        evidence_urls = _product_line_evidence_urls(candidate, snippets)
        if not _secondary_product_line_has_strong_evidence(candidate, score=score, evidence_urls=evidence_urls):
            continue
        add_line(
            candidate,
            _choose_project_subtype(candidate, flags, snippets),
            role="secondary",
            score=score,
        )

    return lines[:6]


def _skip_secondary_product_line(primary_type: str, candidate: str) -> bool:
    if candidate in {"blockchain", "rwa", "data_infra"} and primary_type != candidate:
        return True
    if primary_type == "dex_aggregator" and candidate == "dex_spot":
        return True
    if primary_type == "dex_spot" and candidate == "dex_aggregator":
        return True
    if primary_type == "asset_management" and candidate == "vault_yield":
        return True
    if primary_type == "liquid_staking" and candidate in {"lending", "dex_spot", "asset_management", "vault_yield"}:
        return True
    if primary_type == "ai_network" and candidate in {"liquid_staking", "bridge", "vault_yield", "yield_trading", "gaming", "nft_marketplace"}:
        return True
    if primary_type == "oracle" and candidate in {"liquid_staking", "synthetic_dollar", "dex_spot", "lending", "gaming", "prediction_market"}:
        return True
    return False


def _secondary_product_line_has_strong_evidence(
    candidate: str,
    *,
    score: int,
    evidence_urls: list[str],
) -> bool:
    del candidate
    usable_urls = [url for url in evidence_urls if not _is_classification_excluded_url(url)]
    if any(_is_strict_docs_url(url) for url in usable_urls):
        return True
    return score >= 10 and len(usable_urls) >= 2


def _best_project_overview_sentence(
    snippets: list[dict[str, str]],
    *,
    project_type: str,
    hints: tuple[str, ...],
    exclude_terms: tuple[str, ...],
    fallback: str | None,
) -> str | None:
    preferred_terms = _preferred_terms_for_project_type(project_type)
    preferred_snippets = [
        snippet
        for snippet in snippets
        if any(term in snippet["text"].lower() for term in preferred_terms)
    ]
    return _best_sentence(
        preferred_snippets or snippets,
        hints=hints,
        exclude_terms=exclude_terms,
        fallback=fallback,
    )


def _best_sentence(
    snippets: list[dict[str, str]],
    *,
    hints: tuple[str, ...],
    exclude_terms: tuple[str, ...] = (),
    fallback: str | None = None,
) -> str | None:
    lowered_hints = tuple(hint.lower() for hint in hints)
    lowered_excludes = tuple(term.lower() for term in exclude_terms)
    ranked: list[tuple[int, str]] = []
    for snippet in snippets:
        text = _strip_ascii_art_fragments(snippet["text"])
        if not text:
            continue
        lower = text.lower()
        match_count = sum(1 for hint in lowered_hints if hint in lower)
        if match_count == 0:
            continue
        if lowered_excludes and any(term in lower for term in lowered_excludes):
            continue
        score = match_count * 10
        word_count = len(text.split())
        if 8 <= word_count <= 36:
            score += 6
        elif 6 <= word_count <= 48:
            score += 3
        if any(token in lower for token in (" is ", " are ", " enables ", " allows ", " protocol ", " users ")):
            score += 5
        if any(token in snippet["url"].lower() for token in ("overview", "docs", "documentation", "developers", "tokenomics", "security", "faq")):
            score += 3
        if _looks_like_docs_url(snippet["url"]):
            score += 2
        score -= max(0, abs(word_count - 18) // 6)
        if _is_noise_sentence(text, url=snippet["url"]):
            score -= 20
        ranked.append((score, text[:400]))
    if ranked:
        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked[0][1]
    return fallback


def _strip_ascii_art_fragments(text: str) -> str:
    cleaned = re.sub(r"[╔╗╚╝║═●○•🤖|\\/]{2,}", " ", text)
    cleaned = re.sub(r"(?:[╔╗╚╝║═●○•🤖|\\/]\s*){4,}", " ", cleaned)
    cleaned = _normalize_spaces(cleaned)
    sentence_start = re.search(r"\b[A-Z][A-Za-z0-9._-]{1,48}\s+(?:is|are|enables|allows|lets|provides|offers)\b", cleaned)
    if sentence_start:
        prefix = cleaned[: sentence_start.start()].strip()
        prefix_is_art_label = bool(prefix) and len(prefix.split()) <= 4 and prefix.upper() == prefix
        if any(ch in prefix for ch in "╔╗╚╝║═●○•🤖|\\/") or prefix_is_art_label:
            cleaned = cleaned[sentence_start.start() :]
    return _normalize_spaces(cleaned)


def _collect_risk_factors(snippets: list[dict[str, str]]) -> list[str]:
    risks: list[str] = []
    for snippet in snippets:
        lower = snippet["text"].lower()
        if any(pattern in lower for pattern in _RISK_PATTERNS):
            text = snippet["text"][:240]
            if text not in risks:
                risks.append(text)
    return risks[:8]


def _detect_supported_chains(snippets: list[dict[str, str]], *, project_type: str | None = None) -> list[str]:
    chains: list[str] = []
    deployment_terms = (
        "deployed on",
        "deployed to",
        "available on",
        "available across",
        "supports",
        "supported chains",
        "supported networks",
        "network support",
        "chain deployments",
        "deployed networks",
        "mainnet deployments",
    )
    excluded_url_terms = (
        "guide",
        "guides",
        "integration",
        "integrations",
        "api",
        "quickstart",
        "sdk",
        "developers",
        "developer",
        "deployed-contracts",
        "operatorportal",
        "token-guide",
        "token-guides",
    )
    liquid_staking_extension_url_terms = (
        "vault",
        "vaults",
        "bridge",
        "bridg",
        "wrap",
        "earn",
        "developers",
        "developer",
        "fireblocks",
        "spl-governance",
        "mint-your",
        "recipe",
        "recipes",
        "cookbook",
        "integration",
        "integrations",
        "institution",
        "institutions",
        "use-cases",
    )
    liquid_staking_extension_text_terms = (
        "integrat",
        "integrator",
        "wrapped",
        "bridge",
        "bridged",
        "vault",
        "vaults",
        "lrt",
        "lst",
    )
    dex_aggregator_extension_url_terms = (
        "perps",
        "predict",
        "launch",
        "earn",
        "terminal",
        "telegram-bots",
        "telegrambots",
        "mobile",
        "manage",
    )
    dex_aggregator_core_url_terms = (
        "/trade/swap",
        "swap",
        "ultra-mode",
        "manual-mode",
        "limit-orders",
        "recurring-orders",
    )
    dex_aggregator_core_text_terms = (
        "swap aggregator",
        "dex aggregator",
        "smart order routing",
        "best execution",
        "liquidity sources",
        "routes swaps",
        "token swaps",
    )
    for chain in _CHAIN_NAMES:
        chain_lower = chain.lower()
        for snippet in snippets:
            lowered = snippet["text"].lower()
            lowered_url = (snippet.get("url") or "").lower()
            if chain_lower not in lowered:
                continue
            if any(term in lowered_url for term in excluded_url_terms):
                continue
            if (project_type or "").strip() == "liquid_staking":
                if any(term in lowered_url for term in liquid_staking_extension_url_terms):
                    continue
                if any(term in lowered for term in liquid_staking_extension_text_terms):
                    continue
            if (project_type or "").strip() == "dex_aggregator":
                if any(term in lowered_url for term in dex_aggregator_extension_url_terms):
                    continue
                if not any(term in lowered_url for term in dex_aggregator_core_url_terms) and not any(term in lowered for term in dex_aggregator_core_text_terms):
                    continue
            if not any(term in lowered for term in deployment_terms):
                continue
            if chain not in chains:
                chains.append(chain)
            break
    return chains[:16]


_CLASSIFICATION_EXCLUDED_URL_TERMS = (
    "guide",
    "guides",
    "integration",
    "integrations",
    "api",
    "tutorial",
    "tutorials",
    "evm-tutorials",
    "deployed-contracts",
    "liquidity-positions",
    "bridge-vtao",
    "staking-and-delegation",
    "delegation",
    "keys/wallets",
    "wallets",
    "btcli",
    "emissions",
    "announcements",
    "resources",
    "local-build",
    "subtensor-api/extrinsics",
    "fireblocks",
    "stake-to-marinade",
    "operatorportal",
    "token-guide",
    "token-guides",
    "deployed-contract",
    "security",
    "audit",
    "audits",
    "bug-bounty",
    "bug_bounty",
    "glossary",
    "faq",
    "official-links",
    "press-kit",
    "press_kit",
    "contract-addresses",
    "sdk",
    "anchor-idl",
    "team",
    "roadmap",
    "governance",
    "tokenomics",
    "the-mnde-token",
)


def _is_classification_excluded_url(url: str) -> bool:
    lowered = (url or "").lower()
    return any(term in lowered for term in _CLASSIFICATION_EXCLUDED_URL_TERMS)


def _classification_semantic_snippets(snippets: list[dict[str, str]]) -> list[dict[str, str]]:
    filtered = [
        snippet
        for snippet in snippets
        if not _is_classification_excluded_url(str(snippet.get("url") or ""))
    ]
    if not filtered:
        return []
    docs_like = [
        snippet
        for snippet in filtered
        if _looks_like_docs_url(str(snippet.get("url") or ""))
    ]
    if docs_like:
        return docs_like
    return filtered


def _docs_semantic_snippets(
    snippets: list[dict[str, str]],
    *,
    official_urls: dict[str, list[str]],
) -> list[dict[str, str]]:
    docs_urls = [
        str(url).strip()
        for url in (official_urls.get("docs") or [])
        if str(url).strip() and _is_strict_docs_url(str(url).strip())
    ]
    if not docs_urls:
        return []
    docs_prefixes = {_docs_prefix_for_url(url) for url in docs_urls if _is_http_url(url)}
    results: list[dict[str, str]] = []
    for snippet in snippets:
        url = str(snippet.get("url") or "").strip()
        if not url:
            continue
        if not _is_strict_docs_url(url):
            continue
        if any(url.startswith(prefix) for prefix in docs_prefixes if prefix):
            results.append(snippet)
            continue
    return results


def _detect_key_entities(snippets: list[dict[str, str]], project_type: str) -> list[str]:
    entities: list[str] = []
    hint_map = {
        "perp_dex": ("markets", "positions", "collateral", "vault", "liquidations"),
        "lending": ("markets", "reserves", "collateral", "borrowers", "suppliers"),
        "dex_spot": ("pools", "pairs", "liquidity", "traders", "routes"),
        "dex_aggregator": ("routes", "quotes", "liquidity sources", "solvers", "intents", "aggregators"),
        "agent_platform": ("agents", "agent tokens", "launches", "commerce protocol", "services"),
        "depin_wireless": ("hotspots", "coverage", "data credits", "iot network", "mobile network", "operators"),
        "liquid_staking": ("validators", "staking rewards", "staked tokens", "lst", "lrt", "withdrawals"),
        "asset_management": ("vaults", "strategies", "portfolios", "indexes", "managers", "rebalancing"),
        "nft_marketplace": ("listings", "bids", "collections", "royalties", "creators", "traders"),
        "gaming": ("players", "games", "quests", "assets", "marketplace", "rewards"),
        "social": ("profiles", "followers", "creators", "communities", "social graph"),
        "prediction_market": ("markets", "outcomes", "odds", "resolution", "liquidity"),
        "meme": ("community", "holders", "culture", "token"),
        "ai_network": ("models", "inference", "compute", "miners", "validators", "subnets"),
        "blockchain": ("accounts", "transactions", "ledger", "validators", "assets", "payments"),
        "rwa": ("issuer", "vault", "custodian", "assets", "redemptions"),
        "bridge": ("messages", "endpoints", "oapps", "workers", "chains"),
        "oracle": ("feeds", "oracles", "consumers", "data", "nodes"),
        "synthetic_dollar": ("minting", "redeeming", "backing assets", "custody", "reserve fund"),
        "data_infra": ("clients", "integrations", "queries", "nodes", "datasets"),
        "vault_yield": ("vaults", "strategies", "depositors", "rewards", "positions"),
        "yield_trading": ("markets", "principal tokens", "yield tokens", "liquidity", "positions"),
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
    preferred_terms = _preferred_terms_for_project_type(project_type)
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


def _product_line_evidence_urls(project_type: str, snippets: list[dict[str, str]]) -> list[str]:
    urls: list[str] = []
    preferred_terms = _preferred_terms_for_project_type(project_type)
    for snippet in snippets:
        lower = snippet["text"].lower()
        if preferred_terms and not any(term in lower for term in preferred_terms):
            continue
        url = str(snippet.get("url") or "").strip()
        if url and url not in urls:
            urls.append(url)
        if len(urls) >= 2:
            break
    return urls


def _preferred_terms_for_project_type(project_type: str) -> tuple[str, ...]:
    return {
        "perp_dex": ("perpetual", "open interest", "funding", "order book", "leverage"),
        "lending": ("lending", "borrow", "money market", "collateral"),
        "dex_spot": ("swap", "amm", "liquidity pool", "spot"),
        "dex_aggregator": ("dex aggregator", "swap aggregator", "smart order routing", "liquidity sources", "best execution", "solvers"),
        "agent_platform": ("agent network", "agent engine", "agent tokenization", "ai agent", "agent commerce protocol", "agent launch", "agent tokens"),
        "depin_wireless": ("wireless network", "hotspot", "data credits", "proof of coverage", "iot network", "mobile network"),
        "liquid_staking": ("liquid staking", "liquid restaking", "staked eth", "staking rewards", "lst", "lrt"),
        "asset_management": ("asset management", "managed vault", "portfolio", "structured product", "strategy vault", "rebalancing"),
        "nft_marketplace": ("nft marketplace", "nft trading", "creator royalties", "secondary sales", "listings", "floor price"),
        "gaming": ("gamefi", "web3 game", "gaming", "play-to-earn", "game economy", "players"),
        "social": ("socialfi", "social network", "social graph", "creator economy", "creator token", "fan token"),
        "prediction_market": ("prediction market", "outcome market", "forecast market", "odds", "market resolution"),
        "meme": ("memecoin", "meme coin", "meme token", "community token", "no utility"),
        "ai_network": ("ai network", "inference", "compute marketplace", "gpu compute", "ai models", "subnets"),
        "blockchain": ("layer 1", "layer 2", "rollup", "network", "ledger", "transaction fees", "native currency"),
        "rwa": ("real-world asset", "treasury", "bond", "custodian"),
        "bridge": ("interoperability", "cross-chain", "message", "omnichain", "oapp", "endpoint"),
        "oracle": ("oracle", "price feed", "data feed"),
        "synthetic_dollar": ("synthetic dollar", "stablecoin", "delta-neutral", "backing asset", "custody"),
        "data_infra": ("infrastructure", "rpc", "indexing"),
        "vault_yield": ("vault", "yield strategy", "auto-compound"),
        "yield_trading": ("trade yield", "hedge yield", "yield token", "principal token", "fixed yield", "interest rate"),
    }.get(project_type, ())


def _detect_token_exists(snippets: list[dict[str, str]], tokenomics_present: bool) -> bool | None:
    joined = " ".join(snippet["text"].lower() for snippet in snippets)
    if tokenomics_present:
        return True
    if any(pattern in joined for pattern in _TOKEN_EXISTS_PATTERNS):
        return True
    return None


def _collect_audit_providers(snippets: list[dict[str, str]], *, official_urls: dict[str, list[str]]) -> list[str]:
    providers: list[str] = []
    known = {
        "sherlock": "Sherlock",
        "certik": "CertiK",
        "trail of bits": "Trail of Bits",
        "openzeppelin": "OpenZeppelin",
        "open zeppelin": "OpenZeppelin",
        "halborn": "Halborn",
        "zellic": "Zellic",
        "quantstamp": "Quantstamp",
        "mixbytes": "MixBytes",
        "peckshield": "PeckShield",
        "chainsecurity": "ChainSecurity",
        "cantina": "Cantina",
        "spearbit": "Spearbit",
        "code4rena": "Code4rena",
        "immunefi": "Immunefi",
    }
    haystacks = [snippet["text"].lower() for snippet in snippets]
    haystacks.extend(url.lower() for url in official_urls.get("audits") or [])
    for raw, label in known.items():
        if any(raw in hay for hay in haystacks) and label not in providers:
            providers.append(label)
    return providers[:8]


def _collect_audit_highlights(snippets: list[dict[str, str]]) -> list[str]:
    highlights: list[str] = []
    for snippet in snippets:
        lower = snippet["text"].lower()
        if not any(term in lower for term in ("audit", "audits", "audited", "security review", "bug bounty")):
            continue
        text = snippet["text"][:260]
        if text not in highlights:
            highlights.append(text)
    return highlights[:5]


def _collect_security_highlights(snippets: list[dict[str, str]]) -> list[str]:
    highlights: list[str] = []
    for snippet in snippets:
        lower = snippet["text"].lower()
        if not any(term in lower for term in ("security", "bug bounty", "safety module", "risk", "audits")):
            continue
        text = snippet["text"][:260]
        if text not in highlights:
            highlights.append(text)
    return highlights[:5]


def _collect_topic_points(
    snippets: list[dict[str, str]],
    *,
    include_terms: tuple[str, ...],
    require_terms: tuple[str, ...] = (),
    exclude_terms: tuple[str, ...] = (),
    preferred_url_terms: tuple[str, ...] = (),
    max_items: int = 6,
) -> list[str]:
    ranked: list[tuple[int, str]] = []
    seen: set[str] = set()
    for snippet in snippets:
        text = snippet["text"][:260]
        lower = text.lower()
        if not any(term in lower for term in include_terms):
            continue
        if require_terms and not any(term in lower for term in require_terms):
            continue
        if exclude_terms and any(term in lower for term in exclude_terms):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        score = 0
        score += sum(4 for term in include_terms if term in lower)
        score += sum(3 for term in require_terms if term in lower)
        if preferred_url_terms and any(term in snippet["url"].lower() for term in preferred_url_terms):
            score += 5
        word_count = len(text.split())
        if 7 <= word_count <= 36:
            score += 4
        elif 5 <= word_count <= 48:
            score += 2
        ranked.append((score, text))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [text for _, text in ranked[:max_items]]


def _clean_topic_points(points: list[str], *, topic: str) -> list[str]:
    cleaned: list[str] = []
    for point in points:
        if _is_low_quality_topic_point(point, topic=topic):
            continue
        cleaned.append(point)
    return cleaned


def _is_low_quality_topic_point(text: str, *, topic: str) -> bool:
    lowered = " ".join((text or "").split()).lower()
    if not lowered:
        return True
    generic_noise = (
        "section titled",
        "contract addresses",
        "codebase:",
        "next steps next steps",
        "resources resources",
        "audience & next steps",
        "what to check why it matters",
        "your stablecoins don’t have to sit still",
        "your stablecoins don't have to sit still",
        "put stablecoins to work",
        "market-leading stablecoin yield",
        "world’s largest yield-generating stablecoin",
        "world's largest yield-generating stablecoin",
        "deploy stablecoins into curated sky vaults",
        "accumulate ecosystem tokens",
        "deposit usds to earn governance tokens",
        "suite of stablecoin yield products",
        "sky staking",
        "stake sky tokens",
        "stake sky to earn",
        "through sky.money",
        "access and stake sky",
        "sky stake rate",
        "sky market cap",
        "sky price",
        "accumulated sky fees",
        "non-custodial interface operated by skybase",
        "skybase does not participate",
        "skybase does not custody",
        "no control over sky protocol",
        "no control over protocol parameters",
        "no ability to control or guarantee",
        "market volatility",
        "regulatory changes",
        "outside skybase’s control",
        "outside skybase's control",
        "deposit usds into the stusds module",
        "capital funds loans for sky stakers",
        "sky vault returns are not",
        "deposit usds to earn sky agent governance tokens",
        "ecosystem rewards build your stake",
        "operators powering the sky protocol",
        "borrow usds against staked sky",
        "ecosystem rewards are issued",
        "sky.money does not control",
        "risk-adjusted yield",
        "standard yield by supplying usds",
        "sky agents",
        "ecosystem partners",
        "rewards from sky agents",
        "rewards accrue programmatically",
        "community-wide marketing campaign",
        "community wide marketing campaign",
        "technical checks are completed by various teams",
        "call the create() function",
        "vote delegate factory",
        "factory will deploy",
        "official deployment",
        "external usage and periodic liquidity management",
        "integrations team",
        "custom action plan",
        "email protected",
        "show me more polls",
        "high impact risk parameter",
        "system surplus technical misc",
        "all mkr holders will be able to participate",
        "hatch reserve",
        "ds-chief",
        "lockstake engine",
        "lssky",
        "lockstakemigrator",
        "relock as sky",
        "removal of exit fees",
        "exit fees in the current seal engine",
        "without incurring any additional fees",
        "front-running",
        "single-block composability",
        "surplus auction",
        "fixed surplus quantity",
        "stablecoin between users",
        "sky governance voting portal",
        "vote with or delegate your sky tokens",
        "latest executive",
        "voter-specific activity",
        "delegated sky or mkr amounts",
        "governance upgrade",
        "sky ecosystem governance community has voted",
        "rate updates via fold",
        "present value of that debt with accrued fees",
    )
    if any(term in lowered for term in generic_noise):
        return True
    if topic in {"value_capture", "tokenomics", "token_distribution", "roadmap"} and any(
        term in lowered
        for term in (
            "migrate your own stake",
            "open a new v2",
            "approve sky",
            "collect your position data",
            "unlock collateral",
            "repay your v1 debt",
            "vote delegate",
            "chief v2",
            "chief and polling contracts",
                "mkr-to-sky",
                "mkr to sky",
                "mkr-sky",
                "sole governance token",
                "migrate-old-mkr",
                "converter v2",
                "mkr tokens",
                "iou token",
                "delayed upgrade penalty",
                "fee collection mechanism",
                "converter contract",
                "collect(to)",
                "one-directional conversion",
                "unidirectionally via the mkrtosky function",
            )
    ):
        return True
    if topic == "revenue_model":
        if "gas fees" in lowered:
            return True
        if "fixed decimal-point" in lowered or "fixed decimal point" in lowered:
            return True
        if "rate updates via fold" in lowered or "present value of that debt with accrued fees" in lowered:
            return True
        if "zero fees" in lowered or "no refund" in lowered or "nofee" in lowered:
            return True
        if ("no fee" in lowered or "no fees" in lowered) and not any(
            marker in lowered for marker in ("fee switch", "protocol fees", "performance fees", "revenue from fees")
        ):
            return True
        if "fees cannot be enabled" in lowered or "all fees collected are tracked" in lowered:
            return True
        if "collect function" in lowered or "accumulated sky fees" in lowered:
            return True
        if "consumed on wipe" in lowered or "include stability fees in the wipe" in lowered:
            return True
        if "stablecoin debt multiplier" in lowered:
            return True
        if any(
            term in lowered
            for term in (
                "delayed upgrade penalty",
                "fee collection mechanism",
                "converter contract",
                "collect(to)",
                "collect function",
                "fee parameter",
                "mkr-to-sky conversions",
                "one-directional conversion",
                "unidirectionally via the mkrtosky function",
                "price extrapolation",
            )
        ):
            return True
    return False


def _contains_percentage(text: str) -> bool:
    return bool(re.search(r"\b\d{1,3}(?:\.\d+)?\s*%", text))


def _contains_allocation_pattern(text: str) -> bool:
    lowered = text.lower()
    allocation_terms = ("allocation", "allocates", "allocated", "distribution", "distributed")
    recipient_terms = ("team", "investor", "treasury", "ecosystem", "community", "foundation", "contributors")
    return _contains_percentage(text) and any(term in lowered for term in allocation_terms) and any(term in lowered for term in recipient_terms)


def _contains_fee_flow_pattern(text: str) -> bool:
    lowered = text.lower()
    value_terms = (
        "fees",
        "fee",
        "revenue",
        "protocol revenue",
        "protocol fee",
        "buyback",
        "burn",
        "cash flow",
        "revshare",
        "admin fee",
        "reserve factor",
        "protocol income",
        "interest spread",
        "fee switch",
        "interest paid by borrowers",
        "performance fees",
        "liquidity provider",
        "lp rewards",
        "cake burn",
        "cake buyback",
        "buyback and burn",
    )
    routing_terms = (
        "receive",
        "receives",
        "distributed",
        "distribution",
        "share of",
        "accrue",
        "accrues",
        "redirect",
        "direct",
        "used to",
        "captured",
        "allocated",
        "split",
        "retained",
    )
    recipient_terms = (
        "treasury",
        "stakers",
        "voters",
        "token holders",
        "holders",
        "dao",
        "protocol",
        "buyback",
        "burn",
        "vecrv",
        "reserve",
    )
    return any(term in lowered for term in value_terms) and any(term in lowered for term in routing_terms) and any(term in lowered for term in recipient_terms)


def _boost_scored_points(
    points: list[str],
    *,
    boosters: tuple[tuple[Callable[[str], bool], int], ...],
    max_items: int,
) -> list[str]:
    ranked: list[tuple[int, str]] = []
    for point in points:
        score = 0
        for matcher, weight in boosters:
            try:
                if matcher(point):
                    score += weight
            except Exception:
                continue
        ranked.append((score, point))
    ranked.sort(key=lambda item: item[0], reverse=True)
    deduped: list[str] = []
    seen: set[str] = set()
    for _, point in ranked:
        key = point.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(point)
    return deduped[:max_items]


def _collect_token_utility_points(
    snippets: list[dict[str, str]],
    *,
    target_name: str | None = None,
    ticker: str | None = None,
) -> list[str]:
    points: list[str] = []
    aliases = _build_token_aliases(target_name=target_name, ticker=ticker)
    normalized_ticker = (ticker or "").strip().lower()
    for snippet in snippets:
        lower = snippet["text"].lower()
        has_utility_keyword = any(
            term in lower for term in (
                "govern",
                "governance",
                "voting",
                "staking",
                "stake",
                "rewards",
                "emissions",
                "buyback",
                "buy back",
                "fee rebate",
                "fee discount",
                "safety module",
            )
        )
        if not has_utility_keyword:
            continue
        has_token_anchor = any(term in lower for term in aliases) if aliases else False
        if not has_token_anchor:
            has_token_anchor = any(
                term in lower for term in (
                    "token holders",
                    "holders can vote",
                    "governance token",
                    "staking token",
                    "ve token",
                    " can be locked",
                    "locked for governance",
                )
            )
        if not has_token_anchor:
            continue
        if normalized_ticker and not _contains_token_reference(lower, normalized_ticker):
            if any(term in lower for term in ("usde", "susde", "usdtb")):
                continue
        if any(
            term in lower for term in (
                "supplied tokens are stored",
                "overcollateralised borrowing",
                "governance-approved parameters",
                "publicly accessible smart contracts",
                "supply assets",
                "borrow assets",
                "market-leading stablecoin yield",
                "put stablecoins to work",
                "stablecoins aren’t built to sit still",
                "stablecoins don't have to sit still",
                "sky savings rate",
                "curated sky vaults",
                "sky ecosystem rewards",
                "stake sky tokens to earn",
                "borrow usds against staked sky",
                "non-custodial defi application providing access to sky protocol's suite of stablecoin yield products",
                "non-custodial defi application providing access to sky protocol’s suite of stablecoin yield products",
                "deposit usds to earn governance tokens",
                "sky protocol enables market-leading stablecoin yield",
                "lock function no longer mints iou token balances",
            )
        ):
            continue
        text = snippet["text"][:260]
        if _is_low_quality_topic_point(text, topic="token_utility"):
            continue
        if text not in points:
            points.append(text)
    return points[:6]


def _collect_value_capture_points(
    snippets: list[dict[str, str]],
    *,
    target_name: str | None = None,
    ticker: str | None = None,
) -> list[str]:
    aliases = _build_token_aliases(target_name=target_name, ticker=ticker)
    points = _collect_topic_points(
        snippets,
        include_terms=(
            "fee",
            "fees",
            "revenue",
            "protocol revenue",
            "buyback",
            "buy back",
            "burn",
            "staking",
            "stake",
            "locked",
            "lock",
            "emissions",
            "fee distribution",
            "share of fees",
            "sent towards",
            "sent to",
            "allocated to",
            "revshare",
            "admin fee",
            "reserve factor",
            "fee architecture",
            "protocol income",
            "vecrv",
            "gauge",
            "data credits",
            "data credit",
            "burn and mint",
            "burning hnt",
            "burned for data credits",
            "derived from hnt",
        ),
        require_terms=aliases,
        exclude_terms=("supply assets", "borrow assets", "supplied tokens are stored"),
        preferred_url_terms=("token", "econom", "governance", "treasury", "fees", "fee", "trade", "trading", "swap", "exchange", "pool", "liquidity", "burn", "buyback", "fee-architecture", "data-credit", "data-credits", "hnt", "iot", "mobile"),
        max_items=10,
    )
    points = _clean_topic_points(points, topic="value_capture")
    return _boost_scored_points(
        points,
        boosters=(
            (_contains_fee_flow_pattern, 10),
            (lambda text: "buyback" in text.lower() or "buy back" in text.lower() or "burn" in text.lower(), 6),
            (lambda text: "locked" in text.lower() or "staking" in text.lower(), 3),
            (lambda text: "vecrv" in text.lower() or "admin fee" in text.lower(), 7),
            (lambda text: "data credit" in text.lower() and ("burn" in text.lower() or "derived from hnt" in text.lower()), 10),
            (lambda text: "burn and mint" in text.lower(), 10),
        ),
        max_items=6,
    )


def _collect_tokenomics_points(snippets: list[dict[str, str]]) -> list[str]:
    points = _collect_topic_points(
        snippets,
        include_terms=(
            "max supply",
            "total supply",
            "circulating supply",
            "supply",
            "emissions",
            "emission",
            "vesting",
            "unlock",
            "allocation",
            "allocated",
            "inflation",
            "deflation",
            "burn",
        ),
        exclude_terms=("supply assets", "borrow assets", "liquidity supplied"),
        preferred_url_terms=("token", "econom", "supply", "emission"),
        max_items=10,
    )
    points = _clean_topic_points(points, topic="tokenomics")
    return _boost_scored_points(
        points,
        boosters=(
            (_contains_percentage, 5),
            (lambda text: "max supply" in text.lower() or "total supply" in text.lower() or "circulating supply" in text.lower(), 8),
            (lambda text: "vesting" in text.lower() or "unlock" in text.lower() or "emissions" in text.lower(), 6),
        ),
        max_items=6,
    )


def _collect_token_distribution_points(snippets: list[dict[str, str]]) -> list[str]:
    points = _collect_topic_points(
        snippets,
        include_terms=(
            "allocation",
            "allocates",
            "allocated",
            "distribution",
            "distributed",
            "team",
            "investor",
            "investors",
            "treasury",
            "ecosystem",
            "community",
            "foundation",
        ),
        preferred_url_terms=("token", "econom", "alloc", "distribution"),
        max_items=10,
    )
    points = _clean_topic_points(points, topic="token_distribution")
    return _boost_scored_points(
        points,
        boosters=(
            (_contains_allocation_pattern, 12),
            (_contains_percentage, 6),
            (lambda text: "team" in text.lower() and "investor" in text.lower(), 4),
        ),
        max_items=6,
    )


def _collect_revenue_model_points(snippets: list[dict[str, str]]) -> list[str]:
    points = _collect_topic_points(
        snippets,
        include_terms=(
            "revenue",
            "fees",
            "fee",
            "trading fee",
            "swap fee",
            "routing fee",
            "aggregation fee",
            "marketplace fee",
            "creator fee",
            "royalty",
            "royalties",
            "validator fee",
            "staking fee",
            "operator fee",
            "protocol fee",
            "borrow rate",
            "spread",
            "performance fee",
            "management fee",
            "sequencer fee",
            "gas fee",
            "service fee",
            "stability fee",
            "stability fees",
            "savings rate",
            "sky savings rate",
            "reserve factor",
            "surplus",
            "surplus buffer",
            "liquidation penalty",
            "liquidation penalties",
            "psm fee",
            "psm fees",
            "spread income",
            "interest spread",
            "protocol income",
            "admin fee",
            "fee architecture",
            "creation fee",
            "launch fee",
            "one-time creation fee",
            "tokenization fee",
            "agent commerce fee",
            "transaction fee",
            "marketplace fee",
            "trading tax",
            "tax",
            "agent revenue",
            "inference payments",
            "per-inference payments",
            "interest paid by borrowers",
            "liquidity provider",
            "liquidity providers",
            "lp rewards",
            "cake burn",
            "cake buyback",
            "buyback and burn",
            "routing fees",
            "aggregation fees",
            "marketplace fees",
            "creator royalties",
            "staking fees",
            "validator commission",
            "operator commission",
            "compute fees",
            "inference fees",
            "platform fees",
            "buy back and burn",
            "sent towards",
            "sent to the treasury",
            "fee switch",
            "fee ranging",
            "total interest amount paid by borrowers",
            "portion of the interest paid by borrowers",
            "performance fees",
            "vault creators have the option to set performance fees",
            "yield-market trading fees",
            "yield market trading fees",
            "yt trading fees",
            "pt trading fees",
            "swap fees from yield markets",
            "revenue share",
            "protocol revenue sharing",
            "sPENDLE",
            "data credit",
            "data credits",
            "network usage is paid",
            "wireless data transmissions",
            "data transfer",
            "burn and mint",
            "burning hnt",
            "burned for data credits",
            "derived from hnt",
            "hotspot onboarding",
            "onboarding a hotspot",
        ),
        exclude_terms=("fee rebate", "fee discount"),
        preferred_url_terms=("fees", "fee", "revenue", "trade", "trading", "swap", "exchange", "pool", "liquidity", "route", "routing", "aggregator", "token", "econom", "burn", "buyback", "fee-architecture", "borrow", "lend", "lending", "yield", "pendle", "governance", "stability", "surplus", "psm", "agent", "agents", "launch", "launchpad", "commerce", "data-credit", "data-credits", "hnt", "iot", "mobile", "staking", "validator", "nft", "marketplace", "royalty", "creator", "ai", "compute", "inference"),
        max_items=10,
    )
    points = _clean_topic_points(points, topic="revenue_model")
    return _boost_scored_points(
        points,
        boosters=(
            (lambda text: "revenue comes from" in text.lower() or "protocol revenue comes from" in text.lower(), 10),
            (_contains_fee_flow_pattern, 8),
            (lambda text: "trading fees" in text.lower() or "swap fees" in text.lower() or "management fee" in text.lower(), 4),
            (lambda text: "routing fee" in text.lower() or "aggregation fee" in text.lower(), 8),
            (lambda text: "marketplace fee" in text.lower() or "creator royalties" in text.lower() or "royalties" in text.lower(), 7),
            (lambda text: "staking fee" in text.lower() or "validator commission" in text.lower() or "operator commission" in text.lower(), 7),
            (lambda text: "compute fee" in text.lower() or "inference fee" in text.lower(), 7),
            (lambda text: "cake burn" in text.lower() or "buyback and burn" in text.lower() or "buy back and burn" in text.lower(), 8),
            (lambda text: "liquidity provider" in text.lower() and "fee" in text.lower(), 5),
            (lambda text: "reserve factor" in text.lower() or "admin fee" in text.lower() or "interest spread" in text.lower(), 8),
            (lambda text: "stability fee" in text.lower() or "surplus buffer" in text.lower() or "psm fees" in text.lower(), 8),
            (lambda text: "liquidation penalties" in text.lower() or "spread income" in text.lower(), 6),
            (lambda text: "fee switch" in text.lower() or "interest paid by borrowers" in text.lower(), 8),
            (lambda text: "performance fees" in text.lower() and "vault" in text.lower(), 7),
            (lambda text: "spendle" in text.lower() or "revenue share" in text.lower(), 8),
            (lambda text: "yield" in text.lower() and "fee" in text.lower(), 6),
            (lambda text: ("agent" in text.lower() or "launch" in text.lower()) and any(term in text.lower() for term in ("fee", "tax", "revenue")), 8),
            (lambda text: "creation fee" in text.lower() or "trading tax" in text.lower() or "agent commerce" in text.lower(), 8),
            (lambda text: "data credit" in text.lower() and ("network usage" in text.lower() or "data transfer" in text.lower() or "wireless data" in text.lower() or "burn" in text.lower()), 10),
            (lambda text: "burn and mint" in text.lower() or "burning hnt" in text.lower(), 10),
        ),
        max_items=6,
    )


def _collect_governance_points(
    snippets: list[dict[str, str]],
    *,
    target_name: str | None = None,
    ticker: str | None = None,
) -> list[str]:
    aliases = _build_token_aliases(target_name=target_name, ticker=ticker)
    points = _collect_topic_points(
        snippets,
        include_terms=("governance", "govern", "vote", "voting", "proposal", "delegate", "delegation", "dao", "quorum", "timelock"),
        require_terms=aliases + ("token holders", "holders can vote", "governance token", "ve token"),
        preferred_url_terms=("governance", "vote", "token", "dao"),
        max_items=6,
    )
    return _clean_topic_points(points, topic="governance")[:6]


def _collect_treasury_points(snippets: list[dict[str, str]]) -> list[str]:
    points = _collect_topic_points(
        snippets,
        include_terms=(
            "treasury",
            "reserve",
            "reserves",
            "community fund",
            "ecosystem fund",
            "protocol-owned liquidity",
            "surplus",
            "surplus buffer",
            "pol",
            "grants",
        ),
        preferred_url_terms=("treasury", "governance", "token", "econom", "surplus"),
        max_items=10,
    )
    points = _clean_topic_points(points, topic="treasury")
    return _boost_scored_points(
        points,
        boosters=(
            (_contains_fee_flow_pattern, 10),
            (_contains_percentage, 4),
            (lambda text: "governance" in text.lower() or "dao" in text.lower(), 4),
        ),
        max_items=6,
    )


def _collect_vesting_points(snippets: list[dict[str, str]]) -> list[str]:
    points = _collect_topic_points(
        snippets,
        include_terms=(
            "vesting",
            "vested",
            "unlock",
            "unlocks",
            "cliff",
            "linear",
            "months",
            "years",
            "emissions schedule",
        ),
        preferred_url_terms=("token", "econom", "vesting", "unlock"),
        max_items=10,
    )
    return _boost_scored_points(
        points,
        boosters=(
            (lambda text: "vesting" in text.lower() or "unlock" in text.lower(), 8),
            (lambda text: bool(re.search(r"\b\d+\s*(month|months|year|years)\b", text.lower())), 6),
            (_contains_percentage, 3),
        ),
        max_items=6,
    )


def _collect_treasury_control_points(snippets: list[dict[str, str]]) -> list[str]:
    points = _collect_topic_points(
        snippets,
        include_terms=(
            "treasury",
            "reserves",
            "governance can",
            "dao can",
            "token holders can vote",
            "direct treasury",
            "allocate treasury",
            "treasury governance",
        ),
        preferred_url_terms=("treasury", "governance", "dao"),
        max_items=10,
    )
    points = _clean_topic_points(points, topic="treasury")
    return _boost_scored_points(
        points,
        boosters=(
            (lambda text: "governance can" in text.lower() or "dao can" in text.lower(), 10),
            (lambda text: "treasury" in text.lower() and ("direct" in text.lower() or "allocate" in text.lower() or "control" in text.lower()), 8),
        ),
        max_items=6,
    )


def _collect_fee_recipient_points(snippets: list[dict[str, str]]) -> list[str]:
    points = _collect_topic_points(
        snippets,
        include_terms=(
            "fees",
            "fee",
            "protocol revenue",
            "share of fees",
            "receives",
            "distributed",
            "accrue",
            "accrues",
            "surplus",
            "surplus buffer",
            "buy back",
            "buyback",
            "burn",
            "cake burn",
            "cake buyback",
            "buyback and burn",
            "trading tax",
            "creation fee",
            "agent commerce",
            "agent revenue",
            "inference payments",
        ),
        preferred_url_terms=("fees", "fee", "revenue", "treasury", "token", "governance", "surplus", "trade", "trading", "swap", "exchange", "pool", "liquidity", "burn", "buyback", "agent", "launch", "commerce"),
        max_items=10,
    )
    points = _clean_topic_points(points, topic="revenue_model")
    return _boost_scored_points(
        points,
        boosters=(
            (_contains_fee_flow_pattern, 12),
            (lambda text: "receives" in text.lower() and "fees" in text.lower(), 7),
            (lambda text: "token holders" in text.lower() or "stakers" in text.lower() or "voters" in text.lower() or "treasury" in text.lower(), 5),
            (lambda text: "trading tax" in text.lower() or "agent commerce" in text.lower(), 7),
        ),
        max_items=6,
    )


def _collect_product_token_link_points(
    snippets: list[dict[str, str]],
    *,
    target_name: str | None = None,
    ticker: str | None = None,
) -> list[str]:
    aliases = _build_token_aliases(target_name=target_name, ticker=ticker)
    points = _collect_topic_points(
        snippets,
        include_terms=(
            "emissions",
            "liquidity",
            "governance voting",
            "fee distribution",
            "staking",
            "locked",
            "boost",
            "incentives",
            "route trading activity",
            "direct emissions",
            "base asset",
            "routing currency",
            "agent tokens",
            "deflationary pressure",
            "agentic currency",
        ),
        require_terms=aliases,
        preferred_url_terms=("token", "econom", "governance", "fees", "liquidity"),
        max_items=10,
    )
    points = _clean_topic_points(points, topic="value_capture")
    return _boost_scored_points(
        points,
        boosters=(
            (lambda text: "direct emissions" in text.lower() or "emissions voting" in text.lower(), 9),
            (lambda text: "liquidity" in text.lower() and ("token" in text.lower() or "ve" in text.lower()), 7),
            (_contains_fee_flow_pattern, 4),
            (lambda text: "base asset" in text.lower() or "routing currency" in text.lower() or "agentic currency" in text.lower(), 8),
        ),
        max_items=6,
    )


def _collect_team_points(snippets: list[dict[str, str]]) -> list[str]:
    points = _collect_topic_points(
        snippets,
        include_terms=(
            "founder",
            "founders",
            "co-founder",
            "cofounder",
            "team",
            "advisor",
            "advisors",
            "ceo",
            "cto",
            "core contributor",
            "lead researcher",
        ),
        exclude_terms=("team allocation", "advisory allocation", "community team"),
        preferred_url_terms=("team", "about", "company", "foundation"),
        max_items=6,
    )
    return _clean_topic_points(points, topic="team")[:6]


def _collect_investor_partner_points(snippets: list[dict[str, str]]) -> list[str]:
    points = _collect_topic_points(
        snippets,
        include_terms=(
            "investor",
            "investors",
            "backed by",
            "backed",
            "supported by",
            "partner",
            "partners",
            "partnership",
            "integration",
            "integrated with",
            "strategic",
            "collaboration",
            "fund",
            "funds",
        ),
        exclude_terms=("community fund", "ecosystem fund", "treasury fund"),
        preferred_url_terms=("partners", "investor", "backers", "ecosystem", "integrations"),
        max_items=6,
    )
    return _clean_topic_points(points, topic="investor_partner")[:6]


def _collect_roadmap_points(snippets: list[dict[str, str]]) -> list[str]:
    points = _collect_topic_points(
        snippets,
        include_terms=(
            "roadmap",
            "upcoming",
            "planned",
            "coming soon",
            "next phase",
            "next step",
            "future plans",
            "milestone",
            "milestones",
            "will launch",
            "will introduce",
            "launching",
        ),
        preferred_url_terms=("roadmap", "docs", "overview", "future"),
        max_items=6,
    )
    return _clean_topic_points(points, topic="roadmap")[:6]


def _build_token_aliases(*, target_name: str | None, ticker: str | None) -> tuple[str, ...]:
    aliases: list[str] = []
    normalized_name = (target_name or "").strip().lower()
    normalized_ticker = (ticker or "").strip().lower()
    if normalized_name:
        aliases.extend(
            [
                normalized_name,
                f"{normalized_name} token",
                f"{normalized_name} holders",
            ]
        )
    if normalized_ticker:
        aliases.extend(
            [
                normalized_ticker,
                f"${normalized_ticker}",
                f"ve{normalized_ticker}",
                f"s{normalized_ticker}",
                f"staked {normalized_ticker}",
                f"{normalized_ticker} token",
                f"{normalized_ticker} holders",
                f"{normalized_ticker} can",
                f"{normalized_ticker} is",
            ]
        )
    deduped: list[str] = []
    for alias in aliases:
        if alias and alias not in deduped:
            deduped.append(alias)
    return tuple(deduped)


def _contains_token_reference(text: str, ticker: str) -> bool:
    if not ticker:
        return False
    patterns = (
        rf"\b{re.escape(ticker)}\b",
        rf"\${re.escape(ticker)}\b",
        rf"\bve{re.escape(ticker)}\b",
        rf"\bs{re.escape(ticker)}\b",
        rf"\bstaked {re.escape(ticker)}\b",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _trusted_semantic_snippets(snippets: list[dict[str, str]], *, official_urls: dict[str, list[str]]) -> list[dict[str, str]]:
    trusted_roots = _trusted_project_root_domains_from_official_urls(official_urls)
    if not trusted_roots:
        return snippets
    return [snippet for snippet in snippets if _snippet_is_from_trusted_project_root(snippet, trusted_roots=trusted_roots)]


def _trusted_project_root_domains_from_official_urls(official_urls: dict[str, list[str]]) -> set[str]:
    roots: set[str] = set()
    for key in ("website", "docs", "overview", "product", "tokenomics", "governance", "treasury", "team", "partners", "roadmap", "security", "faq"):
        for url in official_urls.get(key) or []:
            host = (urlparse(str(url)).hostname or "").lower()
            if host:
                roots.add(_registered_domain(url))
    return roots


def _snippet_is_from_trusted_project_root(snippet: dict[str, str], *, trusted_roots: set[str]) -> bool:
    url = str(snippet.get("url") or "").strip()
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    return _registered_domain(url) in trusted_roots


def _is_noise_sentence(text: str, *, url: str) -> bool:
    lowered = text.lower().strip()
    if not lowered:
        return True
    if _looks_like_ascii_art(text):
        return True
    if any(pattern in lowered for pattern in _NOISE_SENTENCE_PATTERNS):
        return True
    if any(part in url.lower() for part in _EXCLUDED_PATH_PARTS):
        return True
    if len(set(re.findall(r"[a-z0-9]+", lowered))) < 4 and len(lowered.split()) < 8:
        return True
    if re.fullmatch(r"[A-Za-z0-9 .,:;/'()_-]+", text) and len(text.split()) <= 6 and not any(ch in text for ch in ".!?"):
        return True
    if len(text.split()) >= 8:
        words = text.split()
        half = len(words) // 2
        if len(words) % 2 == 0 and " ".join(words[:half]).lower() == " ".join(words[half:]).lower():
            return True
    return False


def _looks_like_ascii_art(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    word_count = len(re.findall(r"[A-Za-zА-Яа-я0-9]{2,}", stripped))
    art_chars = sum(1 for ch in stripped if ch in "═║╔╗╚╝●○•|\\/[]{}<>_*-+=#~")
    non_word_chars = sum(1 for ch in stripped if not ch.isalnum() and not ch.isspace())
    if len(stripped) >= 24 and art_chars >= 8 and word_count <= 6:
        return True
    if len(stripped) >= 40 and non_word_chars / max(len(stripped), 1) > 0.45 and word_count <= 10:
        return True
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if len(lines) >= 3 and sum(1 for line in lines if sum(1 for ch in line if ch in "═║╔╗╚╝●○•|\\/") >= 2) >= 2:
        return True
    return False


def _business_model_fallback(project_type: str, subtype: str | None) -> str | None:
    if project_type == "blockchain" and subtype == "payments_tokenization_l1":
        return "Provides a public blockchain network for payments, asset issuance, tokenization, and smart-contract transactions."
    mapping = {
        "perp_dex": "Facilitates perpetual trading markets and monetizes trading activity.",
        "lending": "Connects suppliers and borrowers in onchain credit markets.",
        "dex_spot": "Provides spot exchange liquidity and routing for token trading.",
        "dex_aggregator": "Aggregates swap liquidity and routes orders across DEXs or liquidity sources for better execution.",
        "blockchain": "Provides base-layer or rollup execution and settlement infrastructure.",
        "rwa": "Packages real-world assets into onchain products with issuer and custody workflows.",
        "bridge": "Provides cross-chain messaging and interoperability infrastructure for applications across chains.",
        "oracle": "Supplies external data and pricing infrastructure to onchain applications.",
        "agent_platform": "Provides an AI-agent tokenization and commerce platform where autonomous agents can be launched, owned, and transact onchain.",
        "depin_wireless": "Provides decentralized wireless network infrastructure where hotspots supply IoT or mobile coverage and users pay for network usage.",
        "liquid_staking": "Tokenizes staked or restaked assets so users can keep liquidity while earning staking or restaking rewards.",
        "asset_management": "Provides onchain asset-management products such as managed vaults, portfolios, indexes, or automated strategies.",
        "nft_marketplace": "Provides marketplace infrastructure for NFT minting, listings, bids, and secondary trading.",
        "gaming": "Provides a Web3 gaming economy where players use onchain assets, rewards, or marketplace flows.",
        "social": "Provides SocialFi or creator-network infrastructure around profiles, communities, creators, or social graphs.",
        "prediction_market": "Provides prediction or outcome markets where users trade on event probabilities and market resolution.",
        "meme": "Represents a community or meme token where product utility and business model are usually weak unless documentation states otherwise.",
        "ai_network": "Provides AI infrastructure such as inference, compute, model, agent, or subnet marketplaces.",
        "synthetic_dollar": "Issues a crypto-native synthetic dollar backed by collateral, custody, and hedging infrastructure.",
        "data_infra": "Provides critical developer or data infrastructure used by other protocols.",
        "vault_yield": "Automates vault-based capital allocation into yield strategies.",
        "yield_trading": "Enables users to tokenize, trade, and hedge future yield from DeFi assets.",
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
        "dex_aggregator": "Primary revenue likely comes from routing, aggregation, partner, or execution-related fees.",
        "blockchain": "Primary revenue likely comes from gas or network fees.",
        "rwa": "Primary revenue likely comes from issuance, management, servicing, or spread capture.",
        "bridge": "Primary revenue likely comes from cross-chain messaging, verification, executor, or bridge fees.",
        "oracle": "Primary revenue likely comes from data feed usage and service fees.",
        "agent_platform": "Primary revenue likely comes from agent launch or creation fees, trading taxes, and agent commerce transaction fees.",
        "depin_wireless": "Primary revenue likely comes from network usage paid with data credits, hotspot onboarding fees, and token burn-and-mint mechanics.",
        "liquid_staking": "Primary revenue likely comes from staking or restaking fees, validator commissions, and protocol fee shares on rewards.",
        "asset_management": "Primary revenue likely comes from management fees, performance fees, strategy fees, or product spreads.",
        "nft_marketplace": "Primary revenue likely comes from marketplace trading fees, mint fees, and creator-royalty or platform fee flows.",
        "gaming": "Primary revenue likely comes from marketplace fees, game-asset sales, platform fees, and transaction fees.",
        "social": "Primary revenue likely comes from creator fees, platform fees, subscriptions, social transactions, or marketplace fees.",
        "prediction_market": "Primary revenue likely comes from trading fees, market fees, settlement fees, or spread capture.",
        "ai_network": "Primary revenue likely comes from compute, inference, model, API, or marketplace usage fees.",
        "synthetic_dollar": "Primary revenue likely comes from protocol spread capture, staking demand, and reserve or hedging-related flows.",
        "data_infra": "Primary revenue likely comes from infrastructure usage by clients or protocols.",
        "vault_yield": "Primary revenue likely comes from management and performance fees.",
        "yield_trading": "Primary revenue likely comes from yield-market trading fees, protocol fees, and revenue share mechanics.",
    }
    return mapping.get(project_type)
