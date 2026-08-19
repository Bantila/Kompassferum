import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._types import JSONColumn


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    test_result_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("test_results.id", ondelete="CASCADE"), unique=True, index=True
    )
    # сырой ответ LLM — для отладки и разбора спорных рекомендаций
    ai_response: Mapped[dict[str, Any]] = mapped_column(JSONColumn, default=dict)
    # распарсенный список профессий
    professions: Mapped[list[dict[str, Any]]] = mapped_column(JSONColumn, default=list)
    # slug модели либо "fallback:rule-based"
    model_used: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    test_result: Mapped["TestResult"] = relationship(back_populates="recommendation")  # noqa: F821
