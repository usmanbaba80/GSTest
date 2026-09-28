"""Entrypoint — re-exports FastAPI app so `uvicorn main:app` still works."""

from app.main import app

__all__ = ["app"]
