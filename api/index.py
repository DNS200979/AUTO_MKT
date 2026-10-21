"""Vercel entrypoint for the FastAPI application.

The Vercel Python runtime discovers an ASGI application exposed as ``app``.
Keeping the entrypoint thin lets the same application continue to run locally
with Uvicorn and in production as a Vercel Function.
"""

from src.market_api.main import app

__all__ = ["app"]
