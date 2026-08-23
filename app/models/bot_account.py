import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class BotAccount(Base):
    """Собеседник бота: связка «пользователь мессенджера — аккаунт Компаса».

    Платформа хранится отдельным полем, а не отдельной таблицей: логика бота
    одна на всех, различается только транспорт. Так добавление MAX не потребует
    ни новой таблицы, ни изменения сценариев.
    """

    __tablename__ = "bot_accounts"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_bot_account_platform_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    platform: Mapped[str] = mapped_column(String(16), index=True)  # telegram | max
    external_id: Mapped[str] = mapped_column(String(64), index=True)
    chat_id: Mapped[str] = mapped_column(String(64))
    # пока аккаунт не привязан — здесь None, а link_code ждёт ввода в приложении
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    link_code: Mapped[str | None] = mapped_column(String(8), unique=True, index=True, nullable=True)
    # задача, которую бот сейчас спрашивает: ответ приходит следующим сообщением
    current_task_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # selectin, а не ленивая загрузка: в асинхронном коде обращение к связи
    # «по требованию» падает — данные должны прийти вместе с самой записью
    user: Mapped["User | None"] = relationship(lazy="selectin")  # noqa: F821
