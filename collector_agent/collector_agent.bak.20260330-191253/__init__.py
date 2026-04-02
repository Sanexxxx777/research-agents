"""External collector agent package for ResearchHub v1."""

from collector_agent.http_app import app
from collector_agent.service import CollectorAgentService

__all__ = ["CollectorAgentService", "app"]
