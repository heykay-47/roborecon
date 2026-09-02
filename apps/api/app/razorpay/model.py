import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base import Base
from app.common.enums import RazorpayPaymentStatus


class RazorpayOrder(Base):
    __tablename__ = "razorpay_orders"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batches.id"), nullable=False, index=True
    )
    provider_order_id: Mapped[str] = mapped_column(
        String(40), nullable=False, index=True
    )
    receipt: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    business_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class RazorpayPayment(Base):
    __tablename__ = "razorpay_payments"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batches.id"), nullable=False, index=True
    )
    provider_payment_id: Mapped[str] = mapped_column(
        String(40), nullable=False, index=True
    )
    provider_order_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    receipt: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    status: Mapped[RazorpayPaymentStatus] = mapped_column(
        Enum(RazorpayPaymentStatus), nullable=False
    )
    captured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    business_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class RazorpayRefund(Base):
    __tablename__ = "razorpay_refunds"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batches.id"), nullable=False, index=True
    )
    provider_refund_id: Mapped[str] = mapped_column(
        String(40), nullable=False, index=True
    )
    provider_payment_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    business_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
