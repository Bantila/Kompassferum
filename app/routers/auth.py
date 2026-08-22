"""Регистрация, вход и профиль.

Главный маршрут: регистрация → (если есть код) вступление в класс → тест.
Гостевое прохождение остаётся: тест можно пройти без аккаунта, а потом
зарегистрироваться — прогресс подтянется по guest_max_user_id.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import SchoolClass, User, UserRole
from app.schemas.auth import LoginRequest, ProfileOut, RegisterRequest, TokenResponse
from app.services.security import create_access_token, decode_access_token, hash_password, verify_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _profile(user: User) -> ProfileOut:
    return ProfileOut(
        id=user.id,
        max_user_id=user.max_user_id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        grade=user.grade,
        class_id=user.class_id,
        school_class=user.school_class,
    )


async def get_current_user(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Пользователь из заголовка Authorization: Bearer <token>."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Нужен вход в аккаунт")

    user_id = decode_access_token(authorization.split(" ", 1)[1].strip())
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Токен недействителен — войдите заново")

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Аккаунт не найден или отключён")
    return user


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest, session: AsyncSession = Depends(get_session)
) -> TokenResponse:
    email = payload.email.strip().lower()
    taken = await session.scalar(select(User).where(func.lower(User.email) == email))
    if taken is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Аккаунт с такой почтой уже есть — войдите")

    school_class: SchoolClass | None = None
    if payload.join_code:
        code = payload.join_code.strip().upper()
        school_class = await session.scalar(select(SchoolClass).where(SchoolClass.join_code == code))
        if school_class is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Код класса не найден — проверьте, что ввели верно")

    # если человек проходил тест гостем — переиспользуем его запись,
    # чтобы ответы и история не потерялись при регистрации
    user: User | None = None
    if payload.guest_max_user_id:
        user = await session.scalar(
            select(User).where(User.max_user_id == payload.guest_max_user_id, User.email.is_(None))
        )

    if user is None:
        user = User(max_user_id=f"web_{secrets.token_hex(6)}")
        session.add(user)

    user.email = email
    user.hashed_password = hash_password(payload.password)
    user.full_name = payload.full_name.strip()
    user.grade = payload.grade
    user.role = UserRole(payload.role)
    user.is_active = True
    if school_class is not None:
        user.class_id = school_class.id
        user.school_class = school_class.name

    await session.commit()
    await session.refresh(user)
    logger.info("Регистрация: %s (роль %s)", email, user.role.value)
    return TokenResponse(access_token=create_access_token(user.id), user=_profile(user))


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_session)) -> TokenResponse:
    email = payload.email.strip().lower()
    user = await session.scalar(select(User).where(func.lower(User.email) == email))

    # одинаковый ответ на «нет такого email» и «неверный пароль» —
    # иначе форма входа превращается в проверялку существующих аккаунтов
    if user is None or not user.hashed_password or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверная почта или пароль")
    if not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Аккаунт отключён")

    return TokenResponse(access_token=create_access_token(user.id), user=_profile(user))


@router.get("/me", response_model=ProfileOut)
async def me(user: User = Depends(get_current_user)) -> ProfileOut:
    return _profile(user)
