#!/usr/bin/env python3
"""Compatibility launcher for the authenticated FastAPI application."""

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("BMA_BRIEFING_BIND_HOST", "127.0.0.1"),
        port=int(os.environ.get("BMA_BRIEFING_PORT", "8770")),
        proxy_headers=True,
    )


if __name__ == "__main__":
    main()
