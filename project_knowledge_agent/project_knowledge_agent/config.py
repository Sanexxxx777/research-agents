"""Runtime settings for the Project Knowledge Agent."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    http_timeout_seconds: float
    docs_stage_cap_seconds: float
    docs_cache_dir: str
    docs_cache_ttl_seconds: int
    docs_max_pages: int
    docs_max_seed_pages: int
    official_blog_max_posts: int
    official_blog_max_seed_pages: int


def get_settings() -> Settings:
    return Settings(
        http_timeout_seconds=max(float(os.getenv("PROJECT_KNOWLEDGE_HTTP_TIMEOUT_SECONDS", "12")), 1.0),
        docs_stage_cap_seconds=max(float(os.getenv("PROJECT_KNOWLEDGE_DOCS_STAGE_CAP_SECONDS", "6")), 1.0),
        docs_cache_dir=os.getenv(
            "PROJECT_KNOWLEDGE_DOCS_CACHE_DIR",
            "/tmp/project-knowledge-docs-cache",
        ).strip(),
        docs_cache_ttl_seconds=max(int(os.getenv("PROJECT_KNOWLEDGE_DOCS_CACHE_TTL_SECONDS", "21600")), 60),
        docs_max_pages=max(int(os.getenv("PROJECT_KNOWLEDGE_DOCS_MAX_PAGES", "40")), 5),
        docs_max_seed_pages=max(int(os.getenv("PROJECT_KNOWLEDGE_DOCS_MAX_SEED_PAGES", "12")), 3),
        official_blog_max_posts=max(int(os.getenv("PROJECT_KNOWLEDGE_OFFICIAL_BLOG_MAX_POSTS", "8")), 1),
        official_blog_max_seed_pages=max(int(os.getenv("PROJECT_KNOWLEDGE_OFFICIAL_BLOG_MAX_SEED_PAGES", "6")), 1),
    )
