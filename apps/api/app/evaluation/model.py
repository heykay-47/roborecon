import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base import Base
from app.common.enums import ResultStatus


class EvaluationCase(Base):
    __tablename__ = "evaluation_cases"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batches.id"), nullable=False, index=True
    )
    case_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    scenario_class: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    matchable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    expected_status: Mapped[ResultStatus] = mapped_column(
        Enum(ResultStatus), nullable=False
    )


class GroundTruthLink(Base):
    __tablename__ = "ground_truth_links"

    evaluation_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_cases.id"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
