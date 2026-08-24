"""Схемы блока тестирования."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.recommendation import ProfessionOut


class QuestionOut(BaseModel):
    """Вопрос в том виде, в каком его видит ученик — без correct_index."""

    id: str
    text: str
    type: str | None = None
    skill: str | None = None
    subject: str | None = None
    difficulty: str | None = None
    topic: str | None = None
    options: list[str] | None = None


class QuestionsResponse(BaseModel):
    # справочники отдаём вместе с вопросами, чтобы у фронта не было своей копии
    subject_titles: dict[str, str] = Field(default_factory=dict)
    subject_groups: dict[str, list[str]] = Field(default_factory=dict)
    block_a_interests: list[QuestionOut] = Field(default_factory=list)
    block_b_subjects: list[QuestionOut] = Field(default_factory=list)
    block_c_softskills: list[QuestionOut] = Field(default_factory=list)


class ProgressSaveRequest(BaseModel):
    """Черновик теста: ответы и уже подобранный план блока B."""

    answers: dict[str, Any]
    plan: dict[str, Any] | None = None


class ProgressResponse(BaseModel):
    answers: dict[str, Any] = Field(default_factory=dict)
    plan: dict[str, Any] | None = None
    updated_at: datetime | None = None
    # сколько отвечено — чтобы приложение показало «продолжить» без пересчёта
    answered: int = 0
class PlanRequest(BaseModel):
    """Ответы блока A — по ним подбираются предметы для блока B."""

    answers: dict[str, Any]


class PlannedSubject(BaseModel):
    subject: str
    title: str


class PlanResponse(BaseModel):
    subjects: list[PlannedSubject]
    questions: list[QuestionOut]
    # какой моделью подобрано, либо fallback:rules — приложение показывает это честно
    source: str
    planned_by_model: bool
    # предметы, которые не вошли в план: их можно пройти по желанию
    optional_subjects: list[PlannedSubject]


class CheckAnswerRequest(BaseModel):
    question_id: str
    selected_index: int = Field(ge=0, le=9)
    time_spent_seconds: float | None = Field(
        default=None, ge=0, description="Задел на антифрод-анализ, в скоринге не участвует"
    )


class CheckAnswerResponse(BaseModel):
    question_id: str
    is_correct: bool
    correct_index: int


class TestSubmitRequest(BaseModel):
    max_user_id: str = Field(min_length=1, max_length=128)
    # {"a1": 4, "b1_k1": 1, "b1_k1": {"selected_index": 1, "time_spent_seconds": 12}, ...}
    answers: dict[str, Any]
    full_name: str | None = Field(default=None, max_length=255)
    school_class: str | None = Field(default=None, max_length=16)
    role: Literal["student", "teacher"] = "student"


class ProgressOut(BaseModel):
    answered: int
    total: int
    percent: float
    is_complete: bool


class TestSubmitResponse(BaseModel):
    test_result_id: uuid.UUID
    completed_at: datetime
    progress: ProgressOut
    computed_scores: dict[str, Any]
    recommendations: list[ProfessionOut]
    fallback: bool
    model_used: str
