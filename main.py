import uvicorn
from fastapi import FastAPI

from backend.api.resources import api_lifespan
from backend.api.routes import (
    fetch_router,
    health_router,
    metrics_router,
    upload_router,
)
from backend.logging_config import configure_logging

configure_logging("api")
app = FastAPI(lifespan=api_lifespan)

app.include_router(health_router)
app.include_router(upload_router, prefix="/upload/v1")
app.include_router(fetch_router, prefix="/fetch/v1")
app.include_router(metrics_router, prefix="/metrics/v1")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=6969, log_config=None)
