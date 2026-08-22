"""Схемы регистрации, входа и профиля."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    grade: int | None = Field(default=None, ge=1, le=11)
    role: str = Field(default="student", pattern="^(student|teacher)$")
    # код класса можно указать сразу при регистрации — тогда вступление
    # произойдёт одним шагом, без отдельного экрана
    join_code: str | None = Field(default=None, min_length=4, max_length=8)
    # если человек уже проходил тест гостем — привяжем его прогресс к аккаунту
    guest_max_user_id: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


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
