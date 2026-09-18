import pandas as pd
from uuid import UUID
from typing import Any

from .reader import read_source_dataset
from .mapping import map_headers
from .normalization import normalize_header

from backend.domain.models import SourceDataset, ColumnMap
from backend.redis import RedisCache


class TransformPipeline:
    def __init__(self, mapping_cache: RedisCache, explicit_mapping: dict[str, Any]):
        self.mapping_cache = mapping_cache
        self.explicit_mapping = explicit_mapping or {}

    async def transform(
        self, file_id: UUID, filename: str, file_content: bytes
    ) -> SourceDataset:
        # Read dataset
        dataset = read_source_dataset(
            filename=filename, source_file_id=file_id, file_bytes=file_content
        )

        # Map headers
        explicit_mappings = self.get_explicit_column_maps(headers=dataset.headers)
        qualified_mappings, ambiguous_mappings = map_headers(
            self.mapping_cache, explicit_mappings
        )

        dataframe = pd.DataFrame(dataset.rows)
        dataframe = dataframe.drop(
            [col.original_name for col in ambiguous_mappings], errors="ignore"
        )
        dataframe = dataframe.rename(
            columns={
                col_map.original_name: col_map.mapping_target
                for col_map in qualified_mappings
            }
        )

        return dataframe

    def get_explicit_column_maps(self, headers: list[str]) -> list[ColumnMap]:
        return [
            ColumnMap(
                original_name=header,
                normalized_name=normalize_header(header),
                mapping_target=self.explicit_mapping.get(header),
            )
            for header in headers
        ]
