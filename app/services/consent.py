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

# С 14 лет подросток вправе распоряжаться своими данными сам, до 14 — только
# законный представитель. Сервис для 12–16 лет, так что граница проходит прямо
# посреди аудитории и молча предполагать «сам» нельзя.
ВОЗРАСТ_САМОСТОЯТЕЛЬНОСТИ = 14


class ConsentError(ValueError):
    """Согласие не может быть принято в таком виде."""


# Свежие записи сверху. Второй ключ обязателен: SQLite ставит одинаковый
# granted_at записям, созданным в одну секунду, а сортировать по id нельзя —
# это случайный UUID, и отозванная запись перевешивала бы только что данное
# согласие. Действующая запись при равной дате считается более поздней.
_ПОРЯДОК_ЖУРНАЛА = (Consent.granted_at.desc(), Consent.revoked_at.is_(None).desc())


async def active_for(session: AsyncSession, user_id: uuid.UUID) -> Consent | None:
    """Действующее согласие: последняя запись журнала, если она не отозвана."""
    последняя = await _последняя(session, user_id)
    if последняя is None or последняя.revoked_at is not None:
        return None
    return последняя


async def _последняя(session: AsyncSession, user_id: uuid.UUID) -> Consent | None:
    return await session.scalar(
        select(Consent)
        .where(Consent.user_id == user_id)
        .order_by(*_ПОРЯДОК_ЖУРНАЛА)
        .limit(1)
    )


async def journal(session: AsyncSession, user_id: uuid.UUID) -> list[Consent]:
    """Все записи по человеку, свежие сверху.

    При проверке спрашивают не «согласен ли сейчас», а «когда и на что
    соглашался, когда отзывал» — на это и отвечает журнал.
    """
    return list(
        await session.scalars(
            select(Consent)
            .where(Consent.user_id == user_id)
            .order_by(*_ПОРЯДОК_ЖУРНАЛА)
        )
    )


async def grant(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    version: str = CURRENT_VERSION,
    granted_by: str = "self",
    age: int | None = None,
) -> Consent:
    """Записать согласие. Повторный вызов обновляет редакцию и снимает отзыв."""
    if granted_by not in КТО_ДАЁТ:
        granted_by = "self"

    # Возраст назван самим учеником и ничем не подтверждён — проверить его
    # нечем. Но раз он назван, противоречить ему согласие не должно: «мне 12,
    # согласие даю сам» — это не согласие.
    if age is not None and age < ВОЗРАСТ_САМОСТОЯТЕЛЬНОСТИ and granted_by != "parent":
        raise ConsentError(
            f"До {ВОЗРАСТ_САМОСТОЯТЕЛЬНОСТИ} лет согласие даёт родитель "
            "или другой законный представитель"
        )

    # Новая запись, а не перезапись прежней: иначе история «дал, отозвал, дал
    # снова» стирается, а с ней и доказательство законности обработки.
    действующее = await active_for(session, user_id)
    if действующее is not None:
        if (
            действующее.document_version == version
            and действующее.granted_by == granted_by
            and действующее.age_at_consent == age
        ):
            # то же согласие на ту же редакцию — записывать нечего
            return действующее
        # согласие на новую редакцию закрывает предыдущее
        действующее.revoked_at = datetime.now(timezone.utc)

    согласие = Consent(
        user_id=user_id,
        document_version=version,
        granted_by=granted_by,
        age_at_consent=age,
        granted_at=datetime.now(timezone.utc),
    )
    session.add(согласие)
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

    действующее = await active_for(session, user_id)
    if действующее is not None:
        действующее.revoked_at = datetime.now(timezone.utc)
    else:
        # действующего согласия не было, но отзыв всё равно фиксируем: иначе
        # следующая сдача теста запишет данные как ни в чём не бывало
        сейчас = datetime.now(timezone.utc)
        session.add(
            Consent(
                user_id=user_id,
                document_version=CURRENT_VERSION,
                granted_at=сейчас,
                revoked_at=сейчас,
            )
        )

    await session.flush()
    logger.info("Согласие отозвано, удалено записей: %s", удалено)
    return удалено
