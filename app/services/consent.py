"""Реестр согласий на обработку персональных данных.

152-ФЗ требует не галочку, а подтверждаемый факт: кто, когда и на какую
редакцию документа согласился — и возможность согласие отозвать, после чего
обработка прекращается.

Отзыв здесь не помечает данные, а удаляет их. Пометка «не обрабатывать» при
сохранённых прохождениях — это по-прежнему хранение данных ребёнка, то есть
обработка. Аккаунт остаётся: по нему и удерживается сам факт отзыва.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Consent, Recommendation, TaskAttempt, TestProgress, TestResult

logger = logging.getLogger(__name__)

# Редакция документа. Меняется вместе с текстом согласия — иначе неизвестно,
# с чем именно соглашался человек.
CURRENT_VERSION = "2026-08-25"

# Кто дал согласие. До 14 лет это законный представитель, и в реестре это
# должно быть видно, а не подразумеваться.
КТО_ДАЁТ = ("self", "parent")


async def active_for(session: AsyncSession, user_id: uuid.UUID) -> Consent | None:
    """Действующее согласие пользователя, либо None."""
    согласие = await session.scalar(select(Consent).where(Consent.user_id == user_id))
    if согласие is None or согласие.revoked_at is not None:
        return None
    return согласие


async def grant(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    version: str = CURRENT_VERSION,
    granted_by: str = "self",
) -> Consent:
    """Записать согласие. Повторный вызов обновляет редакцию и снимает отзыв."""
    if granted_by not in КТО_ДАЁТ:
        granted_by = "self"

    согласие = await session.scalar(select(Consent).where(Consent.user_id == user_id))
    if согласие is None:
        согласие = Consent(user_id=user_id, document_version=version, granted_by=granted_by)
        session.add(согласие)
    else:
        согласие.document_version = version
        согласие.granted_by = granted_by
        согласие.granted_at = datetime.now(timezone.utc)
        согласие.revoked_at = None
    await session.flush()
    return согласие


async def revoke(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Отозвать согласие и удалить обработанные данные. Возвращает число записей.

    Удаляем явно, а не полагаясь на каскады внешних ключей: SQLite не включает
    их по умолчанию, и в тестах каскад молча не сработал бы — а это ровно тот
    случай, когда «кажется, удалилось» недопустимо.
    """
    результаты = list(
        await session.scalars(select(TestResult.id).where(TestResult.user_id == user_id))
    )
    удалено = 0
    if результаты:
        удалено += (
            await session.execute(
                delete(Recommendation).where(Recommendation.test_result_id.in_(результаты))
            )
        ).rowcount or 0
        удалено += (
            await session.execute(delete(TestResult).where(TestResult.user_id == user_id))
        ).rowcount or 0

    for таблица in (TestProgress, TaskAttempt):
        удалено += (
            await session.execute(delete(таблица).where(таблица.user_id == user_id))
        ).rowcount or 0

    согласие = await session.scalar(select(Consent).where(Consent.user_id == user_id))
    if согласие is not None:
        согласие.revoked_at = datetime.now(timezone.utc)
    else:
        # согласия не было, но отзыв всё равно фиксируем: иначе следующая сдача
        # теста запишет данные как ни в чём не бывало
        session.add(
            Consent(
                user_id=user_id,
                document_version=CURRENT_VERSION,
                revoked_at=datetime.now(timezone.utc),
            )
        )

    await session.flush()
    logger.info("Согласие отозвано, удалено записей: %s", удалено)
    return удалено
