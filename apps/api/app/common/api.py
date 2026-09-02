from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        from_attributes=True,
        populate_by_name=True,
    )


ItemT = TypeVar("ItemT")


class PaginatedResponse(ApiModel, Generic[ItemT]):
    items: list[ItemT]
    total: int
    page: int = 1
    page_size: int = 50
