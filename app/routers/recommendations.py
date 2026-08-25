"""Выдача сохранённых рекомендаций и истории прохождений."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Recommendation, TestResult, User
from app.schemas.recommendation import RecommendationOut
from app.routers.auth import get_current_user
from app.schemas.user import HistoryItem, UserHistoryResponse, UserOut
from app.services.ai_recommender import FALLBACK_MODEL_NAME

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["recommendations"])


def _top_interests(scores: dict, limit: int = 3) -> list[str]:
    interests = (scores or {}).get("interests") or {}
    return sorted(interests, key=lambda k: interests[k], reverse=True)[:limit]


@router.get("/recommendations/{test_result_id}", response_model=RecommendationOut)
async def get_recommendation(
    test_result_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RecommendationOut:
    """Подбор профессий по результату теста — только своему.

    Индивидуальные рекомендации не видит и педагог: ему полагается
    обезличенная сводка по классу, а не разбор конкретного ребёнка.
    """
    recommendation = await session.scalar(
        select(Recommendation).where(Recommendation.test_result_id == test_result_id)
    )
    if recommendation is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Рекомендации для результата {test_result_id} не найдены",
        )
    test_result = await session.get(TestResult, test_result_id)
    # Тот же 404, что и при отсутствии записи: разные ответы позволили бы
    # перебором выяснять, какие результаты существуют.
    if test_result is None or test_result.user_id != user.id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Рекомендации для результата {test_result_id} не найдены",
        )
    return RecommendationOut(
        id=recommendation.id,
        test_result_id=recommendation.test_result_id,
        professions=recommendation.professions,
        model_used=recommendation.model_used,
        fallback=recommendation.model_used == FALLBACK_MODEL_NAME,
        created_at=recommendation.created_at,
        computed_scores=test_result.computed_scores if test_result else None,
    )


@router.get("/users/{max_user_id}/history", response_model=UserHistoryResponse)
async def get_user_history(
    max_user_id: str,
    requester: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserHistoryResponse:
    """История прохождений — по ней видно, как меняются интересы со временем.

    Только своя. max_user_id — это id пользователя в мессенджере, его несложно
    подобрать перебором, и без проверки история любого ребёнка читалась бы по
    одному угаданному числу.
    """
    user = await session.scalar(select(User).where(User.max_user_id == max_user_id))
    if user is None or user.id != requester.id:
        # одинаковый ответ на «нет такого» и «не ваш»: иначе перебором
        # выясняется, кто вообще пользуется сервисом
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Пользователь {max_user_id!r} не найден"
        )

    results = (
        await session.scalars(
            select(TestResult)
            .where(TestResult.user_id == user.id)
            .order_by(TestResult.completed_at.desc())
        )
    ).all()

    history = [
        HistoryItem(
            test_result_id=result.id,
            completed_at=result.completed_at,
            top_interests=_top_interests(result.computed_scores),
            professions=result.recommendation.professions if result.recommendation else [],
            fallback=bool(
                result.recommendation
                and result.recommendation.model_used == FALLBACK_MODEL_NAME
            ),
        )
        for result in results
    ]

    return UserHistoryResponse(
        user=UserOut(
            id=user.id,
            max_user_id=user.max_user_id,
            role=user.role.value,
            full_name=user.full_name,
            school_class=user.school_class,
            created_at=user.created_at,
        ),
        attempts=len(history),
        history=history,
    )
