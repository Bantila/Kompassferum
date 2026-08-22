import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SchoolClass(Base):
    __tablename__ = "school_classes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(32))
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # код из 6 символов без похожих друг на друга букв/цифр — ученики вводят вручную
    join_code: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    teacher: Mapped["User"] = relationship(  # noqa: F821
        back_populates="taught_classes", foreign_keys=[teacher_id]
    )
    students: Mapped[list["User"]] = relationship(  # noqa: F821
        back_populates="class_ref", foreign_keys="User.class_id"
    )
