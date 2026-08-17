import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._types import JSONColumn


class TestResult(Base):
    __tablename__ = "test_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # сырые ответы: {"a1": 4, "b1_k1": {"selected_index": 1, "time_spent_seconds": 12}, ...}
    raw_answers: Mapped[dict[str, Any]] = mapped_column(JSONColumn, default=dict)
    # результат calculate_scores()
    computed_scores: Mapped[dict[str, Any]] = mapped_column(JSONColumn, default=dict)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="test_results")  # noqa: F821
    recommendation: Mapped["Recommendation | None"] = relationship(  # noqa: F821
        back_populates="test_result", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )
