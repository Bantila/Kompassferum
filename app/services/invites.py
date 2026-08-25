"""Коды приглашения педагогов.

Роль teacher открывает сводку по классу. Пока регистрация была свободной,
эту роль назначал себе сам заявитель — достаточно было почты. Код приглашения
переносит подтверждение на того, кто уже работает в школе.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TeacherInvite, User

logger = logging.getLogger(__name__)

DEFAULT_TTL_DAYS = 14

# Без похожих начертаний: код диктуют голосом и переписывают с бумажки, а
# перепутанные 0/O и 1/I/l превращаются в «код не подходит» на ровном месте.
АЛФАВИТ = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_code() -> str:
    куски = ("".join(secrets.choice(АЛФАВИТ) for _ in range(4)) for _ in range(3))
    return "-".join(куски)


async def create(
    session: AsyncSession,
    *,
    created_by: User | None = None,
    note: str = "",
    ttl_days: int = DEFAULT_TTL_DAYS,
) -> TeacherInvite:
    """Выписать одноразовый код."""
    invite = TeacherInvite(
        code=generate_code(),
        created_by_id=created_by.id if created_by else None,
        note=note.strip()[:120],
        expires_at=datetime.now(timezone.utc) + timedelta(days=ttl_days),
    )
    session.add(invite)
    await session.flush()
    return invite


async def redeem(session: AsyncSession, code: str, user_id) -> bool:
    """Погасить код за пользователем. False — код не подошёл.

    Гасим одним UPDATE с условиями прямо в WHERE, а не «прочитать, проверить,
    записать»: между чтением и записью по одному коду успевают зарегистрироваться
    двое, и одноразовость превращается в фикцию.
    """
    нормализованный = code.strip().upper()
    if not нормализованный:
        return False

    сейчас = datetime.now(timezone.utc)
    результат = await session.execute(
        update(TeacherInvite)
        .where(
            TeacherInvite.code == нормализованный,
            TeacherInvite.used_at.is_(None),
            TeacherInvite.expires_at > сейчас,
        )
        .values(used_at=сейчас, used_by_id=user_id)
    )
    подошёл = результат.rowcount == 1
    if not подошёл:
        logger.info("Код приглашения не подошёл: %s", нормализованный)
    return подошёл
