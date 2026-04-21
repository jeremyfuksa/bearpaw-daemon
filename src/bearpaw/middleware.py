"""Supplementary middleware wiring.

The primary CORS middleware is attached inside `create_app` using the
values in `ApiConfig.cors_origins`, so external consumers only need to
edit config to add new origins. This module adds a catch-all OPTIONS
handler for preflight requests, which CORSMiddleware alone doesn't
always produce the right headers for when the origin isn't in the
allowlist.
"""

from typing import Iterable, Optional

from fastapi import Request
from fastapi.responses import Response


def add_cors_middleware(app, origins: Optional[Iterable[str]] = None) -> None:
    """Attach a permissive OPTIONS preflight handler.

    `origins` is accepted for API-compatibility but currently unused; the
    real CORS allowlist lives in `create_app` / `ApiConfig.cors_origins`.
    """
    allow_list = list(origins) if origins else []

    @app.options("/{path:path}")
    async def options_handler(path: str, request: Request) -> Response:
        origin = request.headers.get("origin", "")
        allow = origin if (not allow_list or origin in allow_list) else "null"
        return Response(
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": allow or "*",
                "Access-Control-Allow-Methods": "*",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Allow-Credentials": "true",
            },
        )
