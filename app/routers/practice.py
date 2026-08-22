"""Тренажёр задач: пак по слабым предметам, проверка ответа с разбором, статистика.

Замыкает петлю продукта: тест «Компаса» говорит, какие предметы подтянуть под
подходящие профессии — тренажёр сразу даёт задачи именно по ним.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Recommendation, TaskAttempt, TestResult, User
from app.routers.auth import get_current_user
from app.schemas.practice import (
    AnswerRequest,
    AnswerResponse,
    PackResponse,
    PracticeStatsResponse,
    ProgressResponse,
    SubjectStat,
    TaskOut,
)
from app.services.ai_recommender import explain_mistake
from app.services.error_classifier import classify
from app.services.gamification import progress_summary, register_answer
from app.services.task_bank import build_pack, get_task, load_tasks, public_task
from app.services.test_scoring import load_questions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/practice", tags=["practice"])

MAX_PACK_SIZE = 20


def _title_to_code() -> dict[str, str]:
    """«Математика» → mathematics: рекомендации хранят названия, банк — коды."""
    return {title.casefold(): code for code, title in load_questions()["subject_titles"].items()}


async def _weak_subjects(session: AsyncSession, user: User) -> list[str]:
    """Предметы для подтягивания из последней рекомендации ученика."""
    recommendation = await session.scalar(
        select(Recommendation)
        .join(TestResult, TestResult.id == Recommendation.test_result_id)
        .where(TestResult.user_id == user.id)
        .order_by(Recommendation.created_at.desc())
        .limit(1)
    )
    if recommendation is None:
        return []

    mapping = _title_to_code()
    subjects: list[str] = []
    for profession in recommendation.professions or []:
        for title in profession.get("subjects_to_improve") or []:
            code = mapping.get(str(title).casefold())
            if code and code not in subjects:
                subjects.append(code)
    return subjects


@router.get("/pack", response_model=PackResponse)
async def get_pack(
    size: int = Query(default=5, ge=1, le=MAX_PACK_SIZE),
    subject: str | None = Query(default=None, description="Один предмет вместо автоподбора"),
    difficulty: str | None = Query(default=None, pattern="^(easy|medium|hard)$"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PackResponse:
    """Пак задач: по слабым предметам ученика, либо по указанному предмету."""
    if subject:
        subjects, reason = [subject], "Ты выбрал этот предмет сам"
    else:
        subjects = await _weak_subjects(session, user)
        reason = (
            "Эти предметы нужны профессиям, которые тебе подошли по тесту"
            if subjects
            else "Пройди тест — тогда пак соберётся под твои профессии. Пока задачи из всех предметов"
        )

    # уже решённые верно не повторяем: незачем гонять по кругу то, что усвоено
    solved = set(
        (
            await session.scalars(
                select(TaskAttempt.task_id).where(
                    TaskAttempt.user_id == user.id, TaskAttempt.is_correct.is_(True)
                )
            )
        ).all()
    )

    tasks = build_pack(subjects=subjects, size=size, difficulty=difficulty, exclude_ids=solved)
    if not tasks:  # всё решено — даём повтор, чтобы тренажёр не упирался в пустоту
        tasks = build_pack(subjects=subjects, size=size, difficulty=difficulty)

    return PackResponse(
        tasks=[TaskOut(**public_task(task)) for task in tasks],
        subjects=sorted({task["subject"] for task in tasks}),
        reason=reason,
    )


@router.post("/answer", response_model=AnswerResponse)
async def submit_answer(
    payload: AnswerRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AnswerResponse:
    """Проверить ответ, разобрать ошибку и сохранить попытку."""
    task = get_task(payload.task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Задача {payload.task_id!r} не найдена")

    verdict = classify(payload.answer, task["answer"], task["subject"])

    attempt = TaskAttempt(
        user_id=user.id,
        task_id=task["id"],
        subject=task["subject"],
        difficulty=task["difficulty"],
        user_answer=payload.answer[:500],
        is_correct=verdict["is_correct"],
        error_type=verdict["error_type"],
        confidence=verdict["confidence"],
    )
    session.add(attempt)
    # достижения считаются по истории попыток, поэтому текущая должна быть уже в ней
    await session.flush()
    reward = await register_answer(
        session, user.id, verdict["is_correct"], datetime.now(UTC).astimezone()
    )
    await session.commit()

    # ИИ объясняет только ошибки: на верном ответе объяснять нечего
    ai_explanation = None
    if not verdict["is_correct"]:
        ai_explanation = await explain_mistake(
            question=task["question"],
            correct_answer=task["answer"],
            user_answer=payload.answer,
            error_label=verdict["error_label"],
            explanation=task["explanation"],
        )

    return AnswerResponse(
        is_correct=verdict["is_correct"],
        correct_answer=task["answer"],
        explanation=task["explanation"],
        error_type=verdict["error_type"],
        error_label=verdict["error_label"],
        recommendation=verdict["recommendation"],
        confidence=verdict["confidence"],
        ai_explanation=ai_explanation,
        **reward,
    )


@router.get("/progress", response_model=ProgressResponse)
async def progress(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
) -> ProgressResponse:
    """Уровень, опыт, серия дней и достижения — для экрана профиля."""
    return ProgressResponse(**await progress_summary(session, user.id))


@router.get("/stats", response_model=PracticeStatsResponse)
async def practice_stats(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
) -> PracticeStatsResponse:
    """Сводка тренировок: точность по предметам и типы ошибок."""
    rows = (
        await session.execute(
            select(
                TaskAttempt.subject,
                func.count(TaskAttempt.id),
                func.count(TaskAttempt.id).filter(TaskAttempt.is_correct.is_(True)),
            )
            .where(TaskAttempt.user_id == user.id)
            .group_by(TaskAttempt.subject)
        )
    ).all()

    by_subject = [
        SubjectStat(
            subject=subject,
            total=total,
            correct=correct,
            accuracy=round(correct / total, 3) if total else 0.0,
        )
        for subject, total, correct in rows
    ]
    total_answered = sum(stat.total for stat in by_subject)
    total_correct = sum(stat.correct for stat in by_subject)

    error_types = (
        await session.scalars(
            select(TaskAttempt.error_type).where(
                TaskAttempt.user_id == user.id, TaskAttempt.is_correct.is_(False)
            )
        )
    ).all()

    return PracticeStatsResponse(
        total_answered=total_answered,
        total_correct=total_correct,
        accuracy=round(total_correct / total_answered, 3) if total_answered else 0.0,
        by_subject=sorted(by_subject, key=lambda s: s.accuracy),
        error_breakdown=dict(Counter(error_types).most_common()),
    )


@router.get("/subjects")
async def subjects() -> dict:
    """Предметы банка задач с названиями и количеством — для выбора в интерфейсе."""
    titles = load_questions()["subject_titles"]
    counter = Counter(task["subject"] for task in load_tasks()["tasks"])
    return {
        "subjects": [
            {"code": code, "title": titles.get(code, code), "tasks": count}
            for code, count in sorted(counter.items(), key=lambda kv: -kv[1])
        ]
    }
