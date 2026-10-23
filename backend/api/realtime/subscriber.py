import asyncio
import json
import logging
import random

import redis.asyncio as redis_async
from pydantic import ValidationError

from backend.api.realtime.hub import RealtimeHub
from backend.api.realtime.messages import MetricsUpdatedPayload
from backend.redis_cache.keys import METRICS_UPDATED_CHANNEL

logger = logging.getLogger(__name__)


async def run_metrics_subscriber(client: redis_async.Redis, hub: RealtimeHub) -> None:
    backoff = 0.5
    while True:
        pubsub = None
        try:
            pubsub = client.pubsub()
            await pubsub.subscribe(METRICS_UPDATED_CHANNEL)
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                backoff = 0.5
                try:
                    payload = MetricsUpdatedPayload.model_validate(
                        json.loads(message["data"])
                    )
                except (ValueError, TypeError, ValidationError):
                    logger.warning("Ignoring malformed metrics pub/sub message")
                    continue
                hub.broadcast_metrics(payload.facility_id, payload.computed_at)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - recover Redis failures
            logger.warning("Metrics pub/sub unavailable: %s", type(exc).__name__)
            await hub.close_all(1013)
            await asyncio.sleep(random.uniform(backoff * 0.75, backoff * 1.25))
            backoff = min(backoff * 2, 30.0)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(METRICS_UPDATED_CHANNEL)
                    await pubsub.aclose()
                except Exception as exc:  # noqa: BLE001 - Redis may already be down
                    logger.debug("Pub/sub cleanup stopped: %s", type(exc).__name__)


__all__ = ["run_metrics_subscriber"]
