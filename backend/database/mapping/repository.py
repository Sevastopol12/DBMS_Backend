from dataclasses import dataclass

from sqlalchemy import select

from backend.database.connection import RDBAsyncConnectionConfig
from backend.database.mapping.schema import HeaderMapping


@dataclass(frozen=True)
class HeaderMappingRow:
    normalized_alias: str
    tier: str
    target: str


class HeaderMappingRepository:
    def __init__(self, config: RDBAsyncConnectionConfig):
        self._session = config.async_session_local

    async def load_active(self) -> tuple[HeaderMappingRow, ...]:
        statement = (
            select(
                HeaderMapping.normalized_alias,
                HeaderMapping.tier,
                HeaderMapping.target,
            )
            .where(HeaderMapping.active.is_(True))
            .order_by(HeaderMapping.normalized_alias, HeaderMapping.tier)
        )
        async with self._session.begin() as session:
            result = await session.execute(statement)
            return tuple(
                HeaderMappingRow(
                    normalized_alias=row.normalized_alias,
                    tier=row.tier,
                    target=row.target,
                )
                for row in result
            )


__all__ = ["HeaderMappingRepository", "HeaderMappingRow"]
