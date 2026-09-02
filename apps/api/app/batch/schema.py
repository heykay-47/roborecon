from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.common.api import ApiModel, PaginatedResponse
from app.common.enums import BatchKind, BatchStatus


class BatchResponse(ApiModel):
    batch_id: UUID = Field(validation_alias="id", serialization_alias="batchId")
    kind: BatchKind
    status: BatchStatus
    seed: str | None
    ground_truth_available: bool
    source_row_count: int
    started_at: datetime | None
    completed_at: datetime | None
    source_counts: dict[str, int] | None = None


class DemoResetResponse(BatchResponse):
    source_counts: dict[str, int]


class BatchListResponse(PaginatedResponse[BatchResponse]):
    pass
