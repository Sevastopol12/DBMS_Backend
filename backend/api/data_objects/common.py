from datetime import datetime
from typing import Annotated

from pydantic import PlainSerializer

from backend.timezone import VIETNAM_TZ, VIETNAM_TZ_NAME

API_DISPLAY_TZ = VIETNAM_TZ_NAME
_API_DISPLAY_ZONE = VIETNAM_TZ


def _serialize_api_datetime(value: datetime) -> str:
    """Serialize metric timestamps in the API's display timezone."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=_API_DISPLAY_ZONE)
    return value.astimezone(_API_DISPLAY_ZONE).isoformat()


ApiDateTime = Annotated[
    datetime,
    PlainSerializer(
        _serialize_api_datetime,
        return_type=str,
        when_used="json",
    ),
]

__all__ = ["API_DISPLAY_TZ", "ApiDateTime", "_serialize_api_datetime"]
