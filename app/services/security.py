"""Пароли и JWT.

Пароли хэшируются bcrypt — в базе никогда не лежит открытый пароль.
Токен носит только user_id: всё остальное читается из БД, чтобы протухшие
данные в токене не расходились с реальностью (сменил класс — токен не врёт).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import get_settings

BCRYPT_MAX_BYTES = 72  # bcrypt обрезает всё длиннее — обрезаем сами и явно


def hash_password(password: str) -> str:
    payload = password.encode("utf-8")[:BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(payload, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        payload = password.encode("utf-8")[:BCRYPT_MAX_BYTES]
        return bcrypt.checkpw(payload, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # битый хэш в базе не должен ронять вход — это просто «пароль не подошёл»
        return False


def create_access_token(user_id: uuid.UUID) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(hours=settings.jwt_ttl_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> uuid.UUID | None:
    """user_id из токена или None, если токен битый/просрочен/подделан."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return uuid.UUID(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None
