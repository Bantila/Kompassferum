"""Схемы регистрации, входа и профиля.

Регистрация по почте осталась только для педагогов: ученик входит
исключительно по подписи мессенджера, поэтому завести себе второй аккаунт
через сайт он больше не может.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    """Регистрация педагога. Роль не принимается из запроса — она всегда teacher."""

    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    # Код приглашения от того, кто уже работает в школе. Без него роль teacher
    # назначал себе сам заявитель, а она открывает сводку по классу.
    invite_code: str = Field(min_length=4, max_length=32)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class MiniAppLoginRequest(BaseModel):
    """Вход из мини-приложения мессенджера — по подписанным данным, без пароля."""

    init_data: str = Field(min_length=1, max_length=4096)
    platform: str = Field(default="telegram", pattern="^(telegram|max)$")


class ProfileOut(BaseModel):
    id: uuid.UUID
    max_user_id: str
    email: str | None = None
    full_name: str | None = None
    role: str
    grade: int | None = None
    class_id: uuid.UUID | None = None
    school_class: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: ProfileOut


class InviteCreateRequest(BaseModel):
    """Кому выписывается код — подпись для списка, не проверяется."""

    note: str = Field(default="", max_length=120)


class InviteOut(BaseModel):
    code: str
    note: str
    expires_at: datetime
    used_at: datetime | None = None
