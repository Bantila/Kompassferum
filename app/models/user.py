import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserRole(str, enum.Enum):
    student = "student"
    teacher = "teacher"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    max_user_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"), default=UserRole.student
    )
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # email/пароль есть только у зарегистрированных: гость проходит тест анонимно,
    # у него max_user_id есть, а учётной записи — нет
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    grade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # денормализованное имя класса (например "7Б") — заполняется при join по коду,
    # источник истины — class_id/SchoolClass, это поле только для быстрых выборок
    school_class: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("school_classes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    test_results: Mapped[list["TestResult"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    # классы, которые ведёт этот пользователь как педагог
    taught_classes: Mapped[list["SchoolClass"]] = relationship(  # noqa: F821
        back_populates="teacher", foreign_keys="SchoolClass.teacher_id"
    )
    # класс, в который вступил этот пользователь как ученик
    class_ref: Mapped["SchoolClass | None"] = relationship(  # noqa: F821
        back_populates="students", foreign_keys=[class_id]
    )
