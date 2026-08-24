import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models._types import JSONColumn


class TestProgress(Base):
    """Незавершённый тест: ответы, данные до отправки результата.

    Раньше прогресс жил только в localStorage, и он терялся вместе с
    браузером: очистил данные, открыл приложение с другого устройства или
    зашёл через бота — тест начинался с нуля. Теперь черновик лежит на
    сервере и привязан к аккаунту.

    Строка одна на ученика: одновременно проходить два теста незачем, а
    завершённые прохождения хранит TestResult.
    """

    __tablename__ = "test_progress"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    # те же сырые ответы, что потом уйдут в TestResult.raw_answers
    answers: Mapped[dict[str, Any]] = mapped_column(JSONColumn, default=dict)
    # план блока B, если он уже подобран — иначе на другом устройстве
    # ученику достался бы другой набор предметов
    plan: Mapped[dict[str, Any]] = mapped_column(JSONColumn, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
