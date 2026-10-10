from .auth import router as auth_router
from .fetch import router as fetch_router
from .health import router as health_router
from .metrics import router as metrics_router
from .ops import router as ops_router
from .upload import router as upload_router

__all__ = [
    "auth_router",
    "fetch_router",
    "health_router",
    "metrics_router",
    "ops_router",
    "upload_router",
]
