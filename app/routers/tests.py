"""Эндпоинты тестирования: выдача вопросов, проверка ответа, приём результатов."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Recommendation, TestProgress, TestResult, User, UserRole
from app.routers.auth import get_current_user
from app.schemas.test import (
    CheckAnswerRequest,
    CheckAnswerResponse,
    ProgressResponse,
    ProgressSaveRequest,
    PlannedSubject,
    PlanRequest,
    PlanResponse,
    QuestionsResponse,
    TestSubmitRequest,
    TestSubmitResponse,
)
from app.services.ai_recommender import FALLBACK_MODEL_NAME, recommend_professions
from app.services import consent as consent_service
from app.services.integrity import check as check_answers
from app.services.test_planner import plan_subjects, questions_for_plan
from app.services.test_scoring import (
    ScoringError,
    calculate_scores,
    completion_progress,
    get_question,
    load_questions,
    public_questions,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tests", tags=["tests"])


@router.get("/questions", response_model=QuestionsResponse)
async def get_questions(
    block: str | None = Query(default=None, description="a | b | c"),
    subject_group: str | None = Query(
        default=None, description="exact | natural | humanities | creative"
    ),
) -> QuestionsResponse:
    """Вопросы для показа ученику.

    correct_index сюда не попадает никогда — иначе правильный ответ виден в
    теле ответа API ещё до того, как ученик выберет вариант.
    Параметры block и subject_group позволяют дробить тест из 74 вопросов
    на короткие сессии («сегодня — точные науки»).
    """
    try:
        return QuestionsResponse(**public_questions(block=block, subject_group=subject_group))
    except ScoringError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/progress", response_model=ProgressResponse)
async def get_progress(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProgressResponse:
    """Незавершённый тест ученика.

    Черновик привязан к аккаунту, а не к браузеру: очистил данные, открыл
    приложение на другом телефоне или зашёл из бота — ответы на месте.
    """
    progress = await session.scalar(
        select(TestProgress).where(TestProgress.user_id == user.id)
    )
    if progress is None:
        return ProgressResponse()

    return ProgressResponse(
        answers=progress.answers or {},
        plan=progress.plan or None,
        updated_at=progress.updated_at,
        answered=len(progress.answers or {}),
    )


@router.put("/progress", response_model=ProgressResponse)
async def save_progress(
    payload: ProgressSaveRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProgressResponse:
    """Сохранить черновик. Ответы приходят целиком и заменяют прежние.

    Слияние здесь было бы вредным: удалить ответ (вернуться назад и
    переотвечать) стало бы невозможно, а два устройства всё равно
    разъезжаются — выигрывает то, где отвечали последним.
    """
    progress = await session.scalar(
        select(TestProgress).where(TestProgress.user_id == user.id)
    )
    if progress is None:
        progress = TestProgress(user_id=user.id)
        session.add(progress)

    progress.answers = payload.answers
    if payload.plan is not None:
        progress.plan = payload.plan

    await session.commit()
    await session.refresh(progress)

    return ProgressResponse(
        answers=progress.answers or {},
        plan=progress.plan or None,
        updated_at=progress.updated_at,
        answered=len(progress.answers or {}),
    )


@router.delete("/progress", status_code=status.HTTP_204_NO_CONTENT)
async def reset_progress(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Начать тест заново."""
    progress = await session.scalar(
        select(TestProgress).where(TestProgress.user_id == user.id)
    )
    if progress is not None:
        await session.delete(progress)
        await session.commit()


@router.post("/plan", response_model=PlanResponse)
async def plan_test(payload: PlanRequest) -> PlanResponse:
    """Подобрать предметы для блока B по ответам блока A.

    Спрашивать все 13 предметов — 52 вопроса, до конца доходят не все. Модель
    смотрит профиль интересов и называет пять предметов, которые стоит
    проверить задачами: блок B сокращается до 15 вопросов, весь тест — до 37.

    Правильные ответы, как и в /questions, сюда не попадают.
    """
    try:
        scores = calculate_scores(payload.answers)
    except ScoringError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    plan = await plan_subjects(scores.get("interests") or {})
    titles = load_questions()["subject_titles"]

    logger.info("План теста: %s (%s)", ", ".join(plan["subjects"]), plan["source"])

    return PlanResponse(
        subjects=[PlannedSubject(subject=c, title=titles.get(c, c)) for c in plan["subjects"]],
        questions=questions_for_plan(plan["subjects"]),
        source=plan["source"],
        planned_by_model=plan["planned_by_model"],
        optional_subjects=[
            PlannedSubject(subject=code, title=title)
            for code, title in titles.items()
            if code not in plan["subjects"]
        ],
    )


@router.post("/check-answer", response_model=CheckAnswerResponse)
async def check_answer(payload: CheckAnswerRequest) -> CheckAnswerResponse:
    """Проверка одного знаниевого вопроса — сравнение происходит на бэкенде."""
    question = get_question(payload.question_id)
    if question is None or question.get("type") != "knowledge":
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Знаниевый вопрос {payload.question_id!r} не найден",
        )
    correct_index = question["correct_index"]
    return CheckAnswerResponse(
        question_id=payload.question_id,
        is_correct=payload.selected_index == correct_index,
        correct_index=correct_index,
    )


@router.post("/submit", response_model=TestSubmitResponse, status_code=status.HTTP_201_CREATED)
async def submit_test(
    payload: TestSubmitRequest, session: AsyncSession = Depends(get_session)
) -> TestSubmitResponse:
    """Приём ответов: считает баллы, зовёт ИИ и сохраняет всё одной транзакцией."""
    try:
        scores = calculate_scores(payload.answers)
    except ScoringError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    user = await session.scalar(select(User).where(User.max_user_id == payload.max_user_id))
    if user is None:
        user = User(
            max_user_id=payload.max_user_id,
            role=UserRole(payload.role),
            full_name=payload.full_name,
            school_class=payload.school_class,
        )
        session.add(user)
        await session.flush()
    else:
        # данные профиля могли уточниться между прохождениями
        if payload.full_name:
            user.full_name = payload.full_name
        if payload.school_class:
            user.school_class = payload.school_class

    # Без записанного согласия прохождение не сохраняем: это данные ребёнка.
    # Проверка стоит после создания пользователя — согласие привязано к нему.
    if await consent_service.active_for(session, user.id) is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Нужно согласие на обработку данных — без него результат не сохраняется",
        )

    integrity = check_answers(payload.answers)
    test_result = TestResult(
        user_id=user.id,
        raw_answers=payload.answers,
        computed_scores=scores,
        integrity=integrity,
    )
    session.add(test_result)
    await session.flush()

    ai_result = await recommend_professions(scores)
    session.add(
        Recommendation(
            test_result_id=test_result.id,
            ai_response=ai_result.get("raw_response") or {},
            professions=ai_result["professions"],
            model_used=ai_result["model_used"],
        )
    )
    # черновик больше не нужен: тест сдан, иначе приложение предложит
    # «продолжить» уже завершённое прохождение
    черновик = await session.scalar(
        select(TestProgress).where(TestProgress.user_id == user.id)
    )
    if черновик is not None:
        await session.delete(черновик)

    await session.commit()
    await session.refresh(test_result)

    logger.info(
        "Тест %s сохранён для пользователя %s (fallback=%s)",
        test_result.id,
        payload.max_user_id,
        ai_result["model_used"] == FALLBACK_MODEL_NAME,
    )

    return TestSubmitResponse(
        test_result_id=test_result.id,
        completed_at=test_result.completed_at,
        progress=completion_progress(payload.answers),
        computed_scores=scores,
        recommendations=ai_result["professions"],
        fallback=ai_result["model_used"] == FALLBACK_MODEL_NAME,
        model_used=ai_result["model_used"],
    )
