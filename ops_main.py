import os

import uvicorn
from fastapi import FastAPI

from backend.api.resources import api_lifespan
from backend.api.routes.ops import router as ops_router
from backend.logging_config import configure_logging

configure_logging("ops")

app = FastAPI(lifespan=api_lifespan)
app.include_router(ops_router, prefix="/ops/v1")


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.getenv("OPS_HOST", "127.0.0.1"),
        port=int(os.getenv("OPS_PORT", "6970")),
        log_config=None,
    )


__all__ = ["app"]
