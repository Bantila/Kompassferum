import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._types import JSONColumn


class ClassAssignment(Base):
    """Задание, выданное классу: набор предметов и размер пака.

    Храним не список конкретных задач, а правило подбора — тогда каждому ученику
    достаются задачи по его слабым местам внутри заданных предметов, а не один
    и тот же список, который можно списать у соседа.
    """

    __tablename__ = "class_assignments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    class_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("school_classes.id", ondelete="CASCADE"), index=True
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(120))
    subjects: Mapped[list[Any]] = mapped_column(JSONColumn, default=list)
    size: Mapped[int] = mapped_column(Integer, default=5)
    difficulty: Mapped[str | None] = mapped_column(String(16), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    school_class: Mapped["SchoolClass"] = relationship()  # noqa: F821
