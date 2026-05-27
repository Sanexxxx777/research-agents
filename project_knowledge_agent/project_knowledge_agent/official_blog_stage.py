"""Official blog/news stage for project knowledge."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from project_knowledge_agent.config import Settings

_BLOCKED_BLOG_HOSTS = (
    "prnewswire.com",
    "cointelegraph.com",
    "coindesk.com",
    "theblock.co",
    "swift.com",
)

_ALLOWED_PUBLISHING_ROOTS = (
    "medium.com",
    "substack.com",
)


@dataclass
class OfficialBlogPost:
    url: str
    title: str
    published_at: datetime | None
    summary: str
    key_points: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    source_name: str = "official_blog"
    source_type: str = "official_blog"


@dataclass
class OfficialBlogStageResult:
    posts: list[OfficialBlogPost]
    citations: list[str]
    status: str
    coverage: dict[str, Any]


class OfficialBlogStage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def collect(self, target: Any, *, client: httpx.AsyncClient, docs_result, period_days: int = 365) -> OfficialBlogStageResult:
        profile = getattr(docs_result, "profile", None)
        if profile is None:
            return OfficialBlogStageResult(
                posts=[],
                citations=[],
                status="partial",
                coverage={"available": False, "reason": "missing_docs_profile"},
            )

        seed_pages = _blog_seed_pages(profile)[: self.settings.official_blog_max_seed_pages]
        if not seed_pages:
            return OfficialBlogStageResult(
                posts=[],
                citations=[],
                status="partial",
                coverage={"available": False, "reason": "no_official_roots"},
            )

        official_hosts = _official_hosts(profile)
        candidate_urls: list[str] = []
        candidate_labels: dict[str, str] = {}
        fetch_errors: list[str] = []

        for seed_url in seed_pages:
            try:
                response = await client.get(
                    seed_url,
                    timeout=self.settings.http_timeout_seconds,
                    follow_redirects=True,
                    headers={"User-Agent": "ProjectKnowledgeAgent/1.0"},
                )
            except Exception as exc:
                fetch_errors.append(f"{seed_url}:{type(exc).__name__}")
                continue
            if response.status_code >= 400:
                fetch_errors.append(f"{seed_url}:http_{response.status_code}")
                continue
            parser = _LinkParser(base_url=str(response.url))
            parser.feed(response.text)
            for url, label in parser.links:
                normalized = _canonical_url(url)
                if not _is_allowed_official_host(normalized, official_hosts):
                    continue
                if _is_blog_hub_url(normalized, label=label):
                    if normalized not in candidate_urls:
                        candidate_urls.append(normalized)
                    if label:
                        candidate_labels[normalized] = label
                    continue
                if _looks_like_blog_post(normalized, label=label):
                    if normalized not in candidate_urls:
                        candidate_urls.append(normalized)
                    if label:
                        candidate_labels[normalized] = label

        expanded_urls: list[str] = []
        expanded_labels: dict[str, str] = {}
        for url in candidate_urls:
            if _looks_like_blog_post(url, label="") and url not in expanded_urls:
                expanded_urls.append(url)
                if candidate_labels.get(url):
                    expanded_labels[url] = candidate_labels[url]
            if not _is_blog_hub_path(url):
                continue
            try:
                response = await client.get(
                    url,
                    timeout=self.settings.http_timeout_seconds,
                    follow_redirects=True,
                    headers={"User-Agent": "ProjectKnowledgeAgent/1.0"},
                )
            except Exception as exc:
                fetch_errors.append(f"{url}:{type(exc).__name__}")
                continue
            if response.status_code >= 400:
                fetch_errors.append(f"{url}:http_{response.status_code}")
                continue
            parser = _LinkParser(base_url=str(response.url))
            parser.feed(response.text)
            for link_url, label in parser.links:
                normalized = _canonical_url(link_url)
                if not _is_allowed_official_host(normalized, official_hosts):
                    continue
                if _looks_like_blog_post(normalized, label=label) and normalized not in expanded_urls:
                    expanded_urls.append(normalized)
                if label:
                    expanded_labels[normalized] = label

        posts: list[OfficialBlogPost] = []
        for url in expanded_urls[: self.settings.official_blog_max_posts * 3]:
            post = await self._fetch_post(
                client=client,
                url=url,
                target=target,
                official_hosts=official_hosts,
                preview_label=expanded_labels.get(url, ""),
            )
            if post is None:
                continue
            posts.append(post)
            if len(posts) >= self.settings.official_blog_max_posts:
                break

        posts = _dedupe_posts(posts)
        posts = _filter_posts_by_period(posts, period_days=period_days)
        posts.sort(key=lambda item: item.published_at or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
        return OfficialBlogStageResult(
            posts=posts,
            citations=[post.url for post in posts],
            status="ok" if posts else "partial",
            coverage={
                "available": True,
                "period_days": period_days,
                "seed_pages": len(seed_pages),
                "candidate_urls": len(candidate_urls),
                "posts_kept": len(posts),
                "fetch_errors": fetch_errors[:20],
            },
        )

    async def _fetch_post(
        self,
        *,
        client: httpx.AsyncClient,
        url: str,
        target: Any,
        official_hosts: set[str],
        preview_label: str,
    ) -> OfficialBlogPost | None:
        try:
            response = await client.get(
                url,
                timeout=self.settings.http_timeout_seconds,
                follow_redirects=True,
                headers={"User-Agent": "ProjectKnowledgeAgent/1.0"},
            )
        except Exception:
            return None
        if response.status_code >= 400:
            return None
        resolved_url = _canonical_url(str(response.url))
        if not _is_allowed_official_host(resolved_url, official_hosts):
            return None
        parser = _ArticleParser(base_url=resolved_url)
        parser.feed(response.text)
        title = _normalize_spaces(parser.title or "")
        text = parser.text()
        preview = _preview_post_from_label(preview_label, target=target)
        if not title and not text and preview is None:
            return None
        shell_like = _looks_generic_site_shell(title=title, text=text)
        if shell_like and preview is None:
            return None
        effective_title = preview["title"] if preview and shell_like else title
        effective_text = preview["summary"] if preview and shell_like else text
        if not _mentions_target(target=target, title=effective_title, text=effective_text):
            return None
        summary = _article_summary(title=effective_title, text=effective_text)
        if not summary and preview is not None:
            summary = preview["summary"]
        if not summary:
            return None
        published_at = _extract_published_at(response.text, url=resolved_url)
        key_points = _key_points(text=effective_text, target=target)
        if not key_points and preview is not None:
            key_points = [preview["summary"]]
        key_points = _dedupe_key_points(key_points, summary=summary)
        return OfficialBlogPost(
            url=resolved_url,
            title=((preview["title"] if preview and shell_like else title) or summary)[:240],
            published_at=published_at,
            summary=summary[:500],
            key_points=[point[:280] for point in key_points[:3]],
            categories=_categorize_post(f"{effective_title} {summary}"),
        )


class _LinkParser(HTMLParser):
    def __init__(self, *, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href")
        if href:
            self._current_href = urljoin(self.base_url, href)
            self._current_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._current_href:
            return
        self.links.append((self._current_href, _normalize_spaces(" ".join(self._current_text))))
        self._current_href = None
        self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href and data.strip():
            self._current_text.append(data.strip())


class _ArticleParser(HTMLParser):
    def __init__(self, *, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title: str = ""
        self._in_title = False
        self._ignore_depth = 0
        self._content_depth = 0
        self._parts: list[str] = []
        self._content_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower_tag = tag.lower()
        if lower_tag in {"script", "style", "noscript", "svg", "nav", "header", "footer", "aside", "button"}:
            self._ignore_depth += 1
            return
        if lower_tag in {"article", "main"}:
            self._content_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        lower_tag = tag.lower()
        if lower_tag in {"script", "style", "noscript", "svg", "nav", "header", "footer", "aside", "button"}:
            self._ignore_depth = max(0, self._ignore_depth - 1)
            return
        if lower_tag in {"article", "main"}:
            self._content_depth = max(0, self._content_depth - 1)
            return
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._ignore_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title += f" {text}"
            return
        if self._content_depth:
            self._content_parts.append(text)
            return
        self._parts.append(text)

    def text(self) -> str:
        if self._content_parts:
            return _normalize_spaces(" ".join(self._content_parts))
        return _normalize_spaces(" ".join(self._parts))


def _blog_seed_pages(profile: Any) -> list[str]:
    urls: list[str] = []
    trusted_roots = _trusted_root_domains(profile)
    official_urls = getattr(profile, "official_urls", {}) or {}
    target_name = str(getattr(profile, "project_name", "") or "").strip().lower()
    for key in ("website", "docs", "blog", "news", "announcements", "updates", "changelog", "medium", "substack"):
        for url in official_urls.get(key) or []:
            normalized = _canonical_url(url)
            if _is_ambiguous_zero_product_url(normalized, target_name=target_name):
                continue
            if normalized and _is_allowed_profile_url(normalized, trusted_roots) and normalized not in urls:
                urls.append(normalized)
    for url in getattr(profile, "docs_urls_read", []) or []:
        normalized = _canonical_url(url)
        if _is_ambiguous_zero_product_url(normalized, target_name=target_name):
            continue
        if normalized and _is_allowed_profile_url(normalized, trusted_roots) and normalized not in urls:
            urls.append(normalized)
    return urls


def _official_hosts(profile: Any) -> set[str]:
    hosts: set[str] = set()
    trusted_roots = _trusted_root_domains(profile)
    official_urls = getattr(profile, "official_urls", {}) or {}
    for group in official_urls.values():
        for url in group or []:
            host = (urlparse(url).hostname or "").lower()
            if host and _is_allowed_profile_url(url, trusted_roots):
                hosts.add(host)
    for url in getattr(profile, "docs_urls_read", []) or []:
        host = (urlparse(url).hostname or "").lower()
        if host and _is_allowed_profile_url(url, trusted_roots):
            hosts.add(host)
    return hosts


def _registered_domain(host: str) -> str:
    parts = [part for part in (host or "").lower().split(".") if part]
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host.lower()


def _trusted_root_domains(profile: Any) -> set[str]:
    roots: set[str] = set()
    official_urls = getattr(profile, "official_urls", {}) or {}
    for key in ("website", "docs"):
        for url in official_urls.get(key) or []:
            host = (urlparse(url).hostname or "").lower()
            if host:
                roots.add(_registered_domain(host))
    for group in official_urls.values():
        for url in group or []:
            host = (urlparse(str(url)).hostname or "").lower()
            host_root = _registered_domain(host)
            if host_root in _ALLOWED_PUBLISHING_ROOTS:
                roots.add(host_root)
    return roots


def _is_allowed_profile_url(url: str, trusted_roots: set[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    path = (urlparse(url).path or "").lower()
    if not host:
        return False
    if any(host == blocked or host.endswith(f".{blocked}") for blocked in _BLOCKED_BLOG_HOSTS):
        return False
    if any(path.endswith(suffix) for suffix in (".png", ".svg", ".jpg", ".jpeg", ".gif", ".webp", ".ico")):
        return False
    if any(token in path for token in ("/brand", "/terms", "/privacy", "/cookie", "/legal", "/images/")):
        return False
    if not trusted_roots:
        return True
    return _registered_domain(host) in trusted_roots


def _is_ambiguous_zero_product_url(url: str, *, target_name: str) -> bool:
    if target_name not in {"zro", "layerzero", "layer zero"}:
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower().rstrip("/")
    if not host.endswith("layerzero.network"):
        return False
    return path in {"/zero", "/blog/zero-thesis", "/zero-thesis"}


def _is_allowed_official_host(url: str, official_hosts: set[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    if host in official_hosts:
        return True
    host_root = _registered_domain(host)
    return any(_registered_domain(item) == host_root for item in official_hosts)


def _canonical_url(url: str | None) -> str:
    text = (url or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if not parsed.scheme or not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/") or "/"
    return parsed._replace(query="", fragment="", path=path).geturl()


def _normalize_spaces(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _is_blog_hub_url(url: str, *, label: str) -> bool:
    haystack = f"{url.lower()} {label.lower()}"
    return any(token in haystack for token in ("/blog", "/news", "/announcements", "/updates", "/changelog", "blog", "news", "announcement", "changelog"))


def _is_blog_hub_path(url: str) -> bool:
    path = (urlparse(url).path or "").lower()
    return any(token in path for token in ("/blog", "/news", "/announcements", "/updates", "/changelog"))


def _looks_like_blog_post(url: str, *, label: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    path = (urlparse(url).path or "").lower()
    if any(
        token in path for token in (
            "/legal",
            "/privacy",
            "/terms",
            "/careers",
            "/brand",
            "/media",
            "/press",
            "/app",
            "/build",
            "/case-studies",
            "/case-studies/",
            "/help",
            "/docs",
            "/faq",
        )
    ):
        return False
    if any(token in path for token in ("/blog/", "/news/", "/announcements/", "/updates/", "/changelog/")):
        return True
    if path in {"/blog", "/news", "/announcements", "/updates", "/changelog"}:
        return False
    if re.search(r"/20\d{2}/\d{2}/", path):
        return True
    if _registered_domain(host) in _ALLOWED_PUBLISHING_ROOTS:
        return len([segment for segment in path.split("/") if segment]) >= 2
    label_text = label.lower()
    if any(token in label_text for token in ("launch", "announcing", "integrat", "partnership", "mainnet", "release", "update")):
        return len([segment for segment in path.split("/") if segment]) >= 2
    return False


def _mentions_target(*, target: Any, title: str, text: str) -> bool:
    haystack = f"{title} {text}".lower()
    names = [str(getattr(target, "name", "") or "").strip()]
    ticker = str(getattr(target, "ticker", "") or "").strip()
    metadata = getattr(target, "metadata", None) or {}
    if isinstance(metadata, dict):
        raw_aliases = metadata.get("aliases") or metadata.get("names") or []
        if isinstance(raw_aliases, str):
            raw_aliases = [raw_aliases]
        names.extend(str(item).strip() for item in raw_aliases if str(item).strip())
    for name in names:
        if len(name) >= 4 and name.lower() in haystack:
            return True
    if ticker and len(ticker) >= 3 and re.search(rf"\b{re.escape(ticker.lower())}\b", haystack):
        return True
    return False


def _extract_published_at(text: str, *, url: str) -> datetime | None:
    patterns = [
        r"article:published_time[\"'\s:=>]+([0-9T:\-+.Z]{10,})",
        r"published[_ -]?at[\"'\s:=>]+([0-9T:\-+.Z]{10,})",
        r"datetime=[\"']([^\"']+)[\"']",
        r"([A-Z][a-z]{2,8}\s+\d{1,2},\s+20\d{2})",
        r"(20\d{2}-\d{2}-\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = match.group(1).strip()
        parsed = _parse_datetime(candidate)
        if parsed is not None:
            return parsed
    parsed = _parse_datetime(url)
    if parsed is not None:
        return parsed
    return None


def _parse_datetime(value: str) -> datetime | None:
    text = (value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    for parser in (
        lambda v: datetime.fromisoformat(v),
        lambda v: datetime.strptime(v, "%B %d, %Y"),
        lambda v: datetime.strptime(v, "%b %d, %Y"),
        lambda v: datetime.strptime(v, "%Y-%m-%d"),
    ):
        try:
            dt = parser(text)
        except Exception:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    url_match = re.search(r"/(20\d{2})/(\d{2})/(\d{2})/", text)
    if url_match:
        return datetime(
            int(url_match.group(1)),
            int(url_match.group(2)),
            int(url_match.group(3)),
            tzinfo=timezone.utc,
        )
    return None


def _article_summary(*, title: str, text: str) -> str:
    sentences = _split_sentences(text)
    for sentence in sentences:
        cleaned = _clean_blog_claim(sentence)
        if cleaned:
            return cleaned
    return _clean_blog_claim(title)


def _key_points(*, text: str, target: Any) -> list[str]:
    points: list[str] = []
    for sentence in _split_sentences(text):
        cleaned = _clean_blog_claim(sentence)
        if not cleaned:
            continue
        if not _mentions_target(target=target, title="", text=cleaned):
            continue
        points.append(cleaned)
        if len(points) >= 3:
            break
    return points


def _split_sentences(text: str) -> list[str]:
    cleaned = _normalize_spaces(text)
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return [part.strip() for part in parts if part.strip()]


def _clean_blog_claim(value: str | None) -> str | None:
    text = _normalize_spaces(value or "")
    if not text:
        return None
    if any(
        token in text.lower()
        for token in (
            "products about blog",
            "blog zero developers",
            "table of contents",
            "13 min read table of contents",
            "company jobs blog support brand",
            "copy as png copy as svg",
            "launch app launch app",
        )
    ):
        return None
    lowered = text.lower()
    if lowered in {
        "aave v3 the original defi protocol.",
        "aave pro v4 the full power of defi.",
        "case studies the best build on aave.",
        "blog the latest news and updates.",
        "aave labs learn about aave labs.",
        "about aave labs learn about aave labs.",
        "products resources developers about aave app savings for everyone.",
    }:
        return None
    if any(token in lowered for token in ("@font-face", "font-family", "font-display", "woff2", "src: url(", "{", "}", "--font-")):
        return None
    if any(token in lowered for token in ("cookie", "privacy", "terms", "subscribe", "all rights reserved", "skip to content")):
        return None
    if any(
        token in lowered for token in (
            "prnewswire",
            "news in focus",
            "all news releases",
            "english-only news releases",
            "news releases overview",
            "multimedia gallery",
            "trending topics",
            "business & money",
            "auto & transportation",
            "according to a post from",
            "reached out to",
            "had not received a response by publication",
        )
    ):
        return None
    if any(
        token in lowered for token in (
            "accessibility statement",
            "skip navigation",
            "investor relations",
            "journalists",
            "agencies",
            "client login",
            "send a release",
            "search search when typing in this field",
            "staff writer reviewed by",
            "cointelegraph in your social feed",
            "follow our",
            "listen 0:00",
            "resources orchestration",
            "docs learn view all resources",
            "docs learn featured",
            "back to changelog",
            "release release",
            "deprecation deprecation",
            "integration integration",
            "docs cross-chain ccip global standard for building secure cross-chain applications",
            "see all changes on github",
            "developers docs builder quick links faucets developer hub",
            "chainlink ecosystem data providers press team circulating supply careers we are hiring",
            "company jobs blog support brand copy as png copy as svg",
            "products consumer vaults markets prime curate rewards infra api sdk",
        )
    ):
        return None
    if any(
        token in lowered for token in (
        "products resources developers about",
        "company jobs blog support brand",
        "products consumer vaults markets prime curate rewards infra api sdk",
        "app savings for everyone",
            "developers about aave",
            "the full power of defi",
            "the best build on aave",
            "case studies",
            "the latest news and updates",
            "learn about aave labs",
            "what is a blockchain",
            "the technology underlying the",
            "decentralization-first",
            "true decentralization is only possible",
            "the zero thesis",
        )
    ):
        return None
    if any(token in lowered for token in ("/// products interoperability", "products about blog zero developers")):
        return None
    if re.match(r"^[A-Z][A-Z\s.,&/-]{12,}$", text):
        return None
    if len(text.split()) < 6:
        return None
    return text[:500]


def _categorize_post(text: str) -> list[str]:
    lowered = text.lower()
    categories: list[str] = []
    mapping = {
        "launch": ("launch", "mainnet", "go-live"),
        "integration": ("integration", "integrates", "integrated"),
        "partnership": ("partnership", "partnered", "collaboration"),
        "governance": ("governance", "proposal", "vote"),
        "security": ("security", "audit", "bug bounty"),
        "tokenomics": ("tokenomics", "emissions", "token"),
        "product_update": ("update", "release", "changelog", "announc"),
    }
    for category, terms in mapping.items():
        if any(term in lowered for term in terms):
            categories.append(category)
    return categories or ["official_update"]


def _dedupe_posts(posts: list[OfficialBlogPost]) -> list[OfficialBlogPost]:
    deduped: list[OfficialBlogPost] = []
    seen: set[tuple[str, str]] = set()
    for post in posts:
        key = (
            _normalize_spaces(post.title).lower(),
            _normalize_spaces(post.summary).lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(post)
    return deduped


def _dedupe_key_points(points: list[str], *, summary: str) -> list[str]:
    deduped: list[str] = []
    seen = {_normalize_spaces(summary).lower()}
    for point in points:
        normalized = _normalize_spaces(point).lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(point)
    return deduped


def _filter_posts_by_period(posts: list[OfficialBlogPost], *, period_days: int) -> list[OfficialBlogPost]:
    cutoff = datetime.now(timezone.utc).timestamp() - (max(int(period_days), 1) * 86400)
    kept: list[OfficialBlogPost] = []
    for post in posts:
        if post.published_at is None:
            continue
        if post.published_at.timestamp() >= cutoff:
            kept.append(post)
    return kept


def _preview_post_from_label(label: str, *, target: Any) -> dict[str, str] | None:
    text = _normalize_spaces(label)
    if not text:
        return None
    cleaned = _clean_blog_claim(text)
    if not cleaned:
        return None
    if not _mentions_target(target=target, title=text, text=text):
        return None
    parts = re.split(r"(?<=[.!?])\s+|\s{2,}", text)
    if len(parts) >= 2:
        title = parts[0].strip()
        summary = " ".join(part.strip() for part in parts[1:] if part.strip())
        summary = _clean_blog_claim(summary) or _clean_blog_claim(text)
    else:
        title, summary = _split_preview_title_summary(text)
    if not title or not summary:
        return None
    if title.lower() == summary.lower():
        return None
    return {"title": title[:240], "summary": summary[:500]}


def _split_preview_title_summary(text: str) -> tuple[str, str]:
    tokens = text.split()
    for idx in range(4, min(len(tokens), 14)):
        title = " ".join(tokens[:idx]).strip()
        summary = " ".join(tokens[idx:]).strip()
        if len(title.split()) >= 3 and len(summary.split()) >= 6:
            cleaned_summary = _clean_blog_claim(summary)
            if cleaned_summary:
                return title, cleaned_summary
    return text[:120], text[:500]


def _looks_generic_site_shell(*, title: str, text: str) -> bool:
    haystack = _normalize_spaces(f"{title} {text}").lower()
    generic_markers = (
        "blog the latest news and updates",
        "aave labs learn about aave labs",
        "products resources developers about",
        "aave app savings for everyone",
        "case studies the best build on aave",
        "company jobs blog support brand",
        "products consumer vaults markets prime curate rewards infra api sdk",
    )
    return sum(1 for marker in generic_markers if marker in haystack) >= 2
