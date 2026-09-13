"""Согласие на обработку персональных данных: посмотреть, дать, отозвать."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import User
from app.routers.auth import get_current_user
from app.schemas.consent import (
    ConsentGrantRequest,
    ConsentJournalOut,
    ConsentRecordOut,
    ConsentRevokedOut,
    ConsentStatusOut,
)
from app.services import consent as service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/consent", tags=["consent"])


@router.get("", response_model=ConsentStatusOut)
async def consent_status(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ConsentStatusOut:
    """Есть ли действующее согласие и на какую редакцию документа."""
    согласие = await service.active_for(session, user.id)
    if согласие is None:
        return ConsentStatusOut(granted=False, current_version=service.CURRENT_VERSION)
    return ConsentStatusOut(
        granted=True,
        current_version=service.CURRENT_VERSION,
        document_version=согласие.document_version,
        granted_by=согласие.granted_by,
        granted_at=согласие.granted_at,
        # текст мог смениться после того, как человек согласился
        outdated=согласие.document_version != service.CURRENT_VERSION,
    )


@router.get("/journal", response_model=ConsentJournalOut)
async def consent_journal(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ConsentJournalOut:
    """Все согласия и отзывы по человеку, свежие сверху.

    При проверке спрашивают не «согласен ли сейчас», а «когда и на что
    соглашался, когда отзывал» — текущее состояние на это не отвечает.
    """
    записи = await service.journal(session, user.id)
    return ConsentJournalOut(
        records=[
            ConsentRecordOut(
                document_version=з.document_version,
                granted_by=з.granted_by,
                age_at_consent=з.age_at_consent,
                granted_at=з.granted_at,
                revoked_at=з.revoked_at,
            )
            for з in записи
        ]
    )


@router.post("", response_model=ConsentStatusOut, status_code=status.HTTP_201_CREATED)
async def grant_consent(
    payload: ConsentGrantRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ConsentStatusOut:
    """Дать согласие. Повторный вызов обновляет редакцию и снимает прежний отзыв."""
    try:
        согласие = await service.grant(
            session,
            user.id,
            version=service.CURRENT_VERSION,
            granted_by=payload.granted_by,
            age=payload.age,
        )
    except service.ConsentError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await session.commit()
    logger.info("Согласие получено: пользователь %s, кем дано %s", user.id, согласие.granted_by)
    return ConsentStatusOut(
        granted=True,
        current_version=service.CURRENT_VERSION,
        document_version=согласие.document_version,
        granted_by=согласие.granted_by,
        granted_at=согласие.granted_at,
        outdated=False,
    )


@router.delete("", response_model=ConsentRevokedOut)
async def revoke_consent(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ConsentRevokedOut:
    """Отозвать согласие и удалить обработанные данные.

    Именно удалить, а не пометить: сохранённые прохождения при отозванном
    согласии — это по-прежнему хранение данных ребёнка.
    """
    удалено = await service.revoke(session, user.id)
    await session.commit()
    return ConsentRevokedOut(revoked=True, deleted_records=удалено)
