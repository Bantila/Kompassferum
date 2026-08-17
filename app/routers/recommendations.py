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
from app.schemas.user import HistoryItem, UserHistoryResponse, UserOut
from app.services.ai_recommender import FALLBACK_MODEL_NAME

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["recommendations"])


def _top_interests(scores: dict, limit: int = 3) -> list[str]:
    interests = (scores or {}).get("interests") or {}
    return sorted(interests, key=lambda k: interests[k], reverse=True)[:limit]


@router.get("/recommendations/{test_result_id}", response_model=RecommendationOut)
async def get_recommendation(
    test_result_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> RecommendationOut:
    recommendation = await session.scalar(
        select(Recommendation).where(Recommendation.test_result_id == test_result_id)
    )
    if recommendation is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Рекомендации для результата {test_result_id} не найдены",
        )
    test_result = await session.get(TestResult, test_result_id)
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
    max_user_id: str, session: AsyncSession = Depends(get_session)
) -> UserHistoryResponse:
    """История прохождений — по ней видно, как меняются интересы со временем."""
    user = await session.scalar(select(User).where(User.max_user_id == max_user_id))
    if user is None:
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
