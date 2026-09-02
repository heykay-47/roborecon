from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.batch.schema import BatchResponse, DemoResetResponse
from app.config import settings
from app.database import get_session
from app.demo.dataset import build_demo_dataset
from app.demo.service import reset_demo, source_counts

router = APIRouter(prefix="/demo", tags=["demo"])


@router.post("/reset", response_model=DemoResetResponse, status_code=status.HTTP_200_OK)
async def reset_demo_endpoint(
    session: AsyncSession = Depends(get_session),
) -> DemoResetResponse:
    if not settings.demo_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo mode is disabled",
        )

    batch = await reset_demo(session)
    dataset = build_demo_dataset(batch.seed or "razorrecon-v1")
    batch_response = BatchResponse.model_validate(batch)
    response_data = batch_response.model_dump()
    response_data["source_counts"] = source_counts(dataset)
    return DemoResetResponse(**response_data)
