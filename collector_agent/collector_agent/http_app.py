"""FastAPI HTTP entrypoint for the external collector agent."""

from __future__ import annotations

from json import JSONDecodeError
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import ValidationError

from collector_agent.config import get_settings
from collector_agent.contracts import CollectorRequest
from collector_agent.normalizer import error_response
from collector_agent.service import CollectorAgentService


def get_service() -> CollectorAgentService:
    return CollectorAgentService()


def create_app() -> FastAPI:
    app = FastAPI(title="collector-agent", version="v1")

    @app.post("/collect")
    async def collect(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except (JSONDecodeError, ValueError):
            response = error_response(
                target=None,
                code="invalid_json",
                message="request body must be valid JSON",
                retryable=False,
            )
            return JSONResponse(status_code=400, content=response.model_dump(mode="json"))

        settings = get_settings()
        inbound_token = request.headers.get("X-Service-Token", "").strip()
        if settings.auth_enabled and inbound_token != settings.service_token:
            response = error_response(
                target=_payload_target(payload),
                code="unauthorized",
                message="invalid X-Service-Token",
                retryable=False,
            )
            return JSONResponse(status_code=401, content=response.model_dump(mode="json"))
        if not settings.auth_enabled:
            logger.debug("[collector_agent] COLLECTOR_SERVICE_TOKEN is empty, auth disabled for local/dev use")

        try:
            collector_request = CollectorRequest.model_validate(payload)
        except ValidationError as exc:
            response = error_response(
                target=_payload_target(payload),
                code="invalid_request",
                message="request payload did not match collector contract",
                retryable=False,
                details=exc.errors(),
            )
            return JSONResponse(status_code=400, content=response.model_dump(mode="json"))

        try:
            service = get_service()
            response = await service.collect(collector_request)
            return JSONResponse(status_code=200, content=response.model_dump(mode="json"))
        except Exception as exc:
            logger.exception("[collector_agent] unhandled /collect failure")
            response = error_response(
                target=payload.get("target") if isinstance(payload, dict) else None,
                code="internal_error",
                message=str(exc) or exc.__class__.__name__,
                retryable=True,
            )
            return JSONResponse(status_code=500, content=response.model_dump(mode="json"))

    return app


def _payload_target(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    target = payload.get("target")
    if isinstance(target, dict):
        return target
    return None


app = create_app()
