"""Сводка по классу для педагога — только агрегаты, без персональных данных."""

from __future__ import annotations

import logging
from collections import Counter, defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import TestResult, User, UserRole
from app.schemas.user import ClassSummaryResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/teacher", tags=["teacher"])

MIN_STUDENTS_FOR_SUMMARY = 3


@router.get("/{teacher_max_id}/class-summary", response_model=ClassSummaryResponse)
async def class_summary(
    teacher_max_id: str,
    school_class: str = Query(min_length=1, max_length=16, description="Например: 7Б"),
    session: AsyncSession = Depends(get_session),
) -> ClassSummaryResponse:
    """Агрегированная картина по классу: куда тянет ребят и где проседают знания.

    Имена, id учеников и индивидуальные рекомендации сюда не попадают.

    TODO (после MVP): проверять, что teacher_max_id действительно закреплён за
    этим классом, и отдавать только данные тех учеников, чьи родители дали
    согласие на обработку — сейчас согласия нигде не хранятся.
    """
    teacher = await session.scalar(select(User).where(User.max_user_id == teacher_max_id))
    if teacher is None or teacher.role != UserRole.teacher:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Сводка доступна только пользователю с ролью teacher",
        )

    results = (
        await session.scalars(
            select(TestResult)
            .join(User, User.id == TestResult.user_id)
            .where(User.school_class == school_class, User.role == UserRole.student)
        )
    ).all()

    students = {result.user_id for result in results}
    if len(students) < MIN_STUDENTS_FOR_SUMMARY:
        # k-анонимность: на двух учениках «агрегат» — это персональные данные
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"В классе {school_class} тест прошли {len(students)} чел. — "
            f"сводка формируется от {MIN_STUDENTS_FOR_SUMMARY}",
        )

    categories: Counter[str] = Counter()
    professions: Counter[str] = Counter()
    interests: defaultdict[str, list[float]] = defaultdict(list)
    softskills: defaultdict[str, list[float]] = defaultdict(list)
    knowledge: defaultdict[str, list[float]] = defaultdict(list)

    for result in results:
        scores = result.computed_scores or {}
        for key, values in (scores.get("interests") or {}).items():
            interests[key].append(float(values))
        for key, values in (scores.get("softskills") or {}).items():
            softskills[key].append(float(values))
        for subject, data in (scores.get("subjects") or {}).items():
            if isinstance(data, dict) and data.get("knowledge_score") is not None:
                knowledge[subject].append(float(data["knowledge_score"]))

        if result.recommendation:
            for profession in result.recommendation.professions or []:
                categories[profession.get("category", "не указана")] += 1
                professions[profession.get("name", "—")] += 1

    weakest = sorted(
        (
            {"subject": subject, "average_knowledge": round(sum(v) / len(v), 2)}
            for subject, v in knowledge.items()
        ),
        key=lambda item: item["average_knowledge"],
    )[:5]

    return ClassSummaryResponse(
        school_class=school_class,
        students_tested=len(students),
        tests_completed=len(results),
        category_distribution=dict(categories.most_common()),
        top_professions=[{"name": name, "count": count} for name, count in professions.most_common(5)],
        average_interests={k: round(sum(v) / len(v), 2) for k, v in interests.items()},
        average_softskills={k: round(sum(v) / len(v), 2) for k, v in softskills.items()},
        weakest_subjects=weakest,
    )
