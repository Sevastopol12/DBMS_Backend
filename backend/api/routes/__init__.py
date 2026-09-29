from .fetch import router as fetch_router
from .metrics import router as metrics_router
from .upload import router as upload_router

__all__ = ["fetch_router", "metrics_router", "upload_router"]
