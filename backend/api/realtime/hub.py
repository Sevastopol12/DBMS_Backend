import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from fastapi import WebSocket

from backend.api.realtime.messages import MetricsUpdated, OutgoingFrame

logger = logging.getLogger(__name__)
_QUEUE_SIZE = 16


@dataclass(eq=False)
class Connection:
    websocket: WebSocket
    facility_id: UUID
    sid: str
    cid: str | None = None
    queue: asyncio.Queue[OutgoingFrame] = field(
        default_factory=lambda: asyncio.Queue(_QUEUE_SIZE)
    )
    writer_task: asyncio.Task | None = None
    client_disconnected: bool = False

    def enqueue(self, message: OutgoingFrame) -> None:
        if self.queue.full():
            queued = []
            dropped = False
            while not self.queue.empty():
                oldest = self.queue.get_nowait()
                if not dropped and isinstance(oldest, MetricsUpdated):
                    dropped = True
                else:
                    queued.append(oldest)
            for item in queued:
                self.queue.put_nowait(item)
            for _ in range(len(queued) + int(dropped)):
                self.queue.task_done()
            if not dropped:
                return
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            return

    async def writer(self) -> None:
        try:
            while True:
                message = await self.queue.get()
                try:
                    await self.websocket.send_text(message.model_dump_json())
                finally:
                    self.queue.task_done()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - socket may disappear at any send
            logger.debug("WebSocket writer stopped: %s", type(exc).__name__)


class RealtimeHub:
    def __init__(self) -> None:
        self._by_facility: dict[UUID, set[Connection]] = {}
        self._connections: set[Connection] = set()

    def connect(
        self, websocket: WebSocket, facility_id: UUID, sid: str, cid: str | None = None
    ) -> Connection:
        connection = Connection(websocket, facility_id, sid, cid)
        connection.writer_task = asyncio.create_task(connection.writer())
        self._connections.add(connection)
        self._by_facility.setdefault(facility_id, set()).add(connection)
        return connection

    def broadcast_metrics(self, facility_id: UUID, computed_at: datetime) -> None:
        frame = MetricsUpdated(facility_id=facility_id, computed_at=computed_at)
        for connection in tuple(self._by_facility.get(facility_id, ())):
            connection.enqueue(frame)

    def send(self, connection: Connection, message: OutgoingFrame) -> None:
        connection.enqueue(message)

    async def flush(self, connection: Connection) -> None:
        try:
            await asyncio.wait_for(connection.queue.join(), timeout=0.25)
        except TimeoutError:
            return

    async def disconnect(self, connection: Connection, code: int = 1000) -> None:
        self._remove(connection)
        task = connection.writer_task
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if not connection.client_disconnected:
            try:
                await connection.websocket.close(code=code)
            except Exception as exc:  # noqa: BLE001 - connection may already be closed
                logger.debug("WebSocket close stopped: %s", type(exc).__name__)

    async def disconnect_session(self, sid: str) -> None:
        await asyncio.gather(
            *(
                self.disconnect(connection, 4401)
                for connection in tuple(self._connections)
                if connection.sid == sid
            ),
            return_exceptions=True,
        )

    async def disconnect_chain(self, sid: str, cid: str) -> None:
        await asyncio.gather(
            *(
                self.disconnect(connection, 4401)
                for connection in tuple(self._connections)
                if connection.sid == sid and connection.cid == cid
            ),
            return_exceptions=True,
        )

    async def close_all(self, code: int = 1013) -> None:
        await asyncio.gather(
            *(
                self.disconnect(connection, code)
                for connection in tuple(self._connections)
            ),
            return_exceptions=True,
        )

    def _remove(self, connection: Connection) -> None:
        self._connections.discard(connection)
        group = self._by_facility.get(connection.facility_id)
        if group is not None:
            group.discard(connection)
            if not group:
                self._by_facility.pop(connection.facility_id, None)


__all__ = ["Connection", "RealtimeHub"]
