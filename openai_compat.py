#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenAI Chat Completions compatible server (system-prompt flavored)

Startup entrypoint that exposes the modular app implemented in protobuf2openai.
"""

from __future__ import annotations

import os
import asyncio

from protobuf2openai.app import app  # FastAPI app


if __name__ == "__main__":
    import uvicorn
    import config
    # Refresh JWT on startup before running the server
    try:
        from warp2protobuf.core.auth import refresh_jwt_if_needed as _refresh_jwt
        asyncio.run(_refresh_jwt())
    except Exception:
        pass
    uvicorn.run(
        app,
        host=os.getenv("HOST", config.OPENAI_COMPAT_HOST),
        port=int(os.getenv("PORT", config.OPENAI_COMPAT_PORT)),
        log_level=config.LOG_LEVEL.lower(),
    )
