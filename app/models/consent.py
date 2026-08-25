"""Согласие на обработку персональных данных.

152-ФЗ требует не «галочку где-то нажали», а подтверждаемый факт: кто, когда и
на какую редакцию документа согласился, и возможность согласие отозвать.
Сводка по классу обезличена, но сами прохождения — данные конкретного ребёнка.

Таблица — журнал, а не текущее состояние: строка на каждое данное согласие,
дата отзыва проставляется в ней же. Состояние выводится как последняя строка
без отзыва.

Так и должно быть: при проверке спрашивают не «согласен ли сейчас», а «когда
и на что соглашался, когда отзывал». Перезапись одной строки эту историю
стирала — а вместе с ней и доказательство, что данные обрабатывались законно.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Consent(Base):
    __tablename__ = "consents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # не unique: у человека столько строк, сколько раз он давал согласие
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    # Редакция документа. Без неё согласие бессмысленно: текст меняется, и надо
    # знать, с чем именно человек соглашался.
    document_version: Mapped[str] = mapped_column(String(32))

    # Кто дал согласие: сам ученик или законный представитель. Для детей до 14
    # согласие даёт родитель, и это должно быть видно в реестре.
    granted_by: Mapped[str] = mapped_column(String(16), default="self")

    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # NULL — согласие действует. Дата — отозвано, обработка прекращена.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
