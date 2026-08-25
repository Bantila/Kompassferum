"""Код приглашения педагога.

Сводка по классу — это данные о детях, пусть и обезличенные. Пока регистрация
была открытой, любой человек с почтой заводил себе роль teacher и получал к ним
доступ. Код приглашения делает роль подтверждённой: её выдаёт тот, кто уже
работает в школе, а не сам заявитель.

Код одноразовый. Многоразовый рано или поздно расходится по переписке и
перестаёт что-либо подтверждать.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TeacherInvite(Base):
    __tablename__ = "teacher_invites"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)

    # Кем выдан. NULL — загрузочный код из консоли сервера: первого педагога
    # пригласить некому, а открывать ради него дыру в регистрации нельзя.
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # для кого выписан — чтобы в списке было видно, чей это код
    note: Mapped[str] = mapped_column(String(120), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    used_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
