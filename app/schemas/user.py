"""Схемы пользователя, истории и сводки для педагога."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.recommendation import ProfessionOut


class UserOut(BaseModel):
    id: uuid.UUID
    max_user_id: str
    role: str
    full_name: str | None = None
    school_class: str | None = None
    created_at: datetime


class HistoryItem(BaseModel):
    test_result_id: uuid.UUID
    completed_at: datetime
    # топ-3 интереса по Голланду — по ним видно динамику между прохождениями
    top_interests: list[str] = Field(default_factory=list)
    professions: list[ProfessionOut] = Field(default_factory=list)
    fallback: bool = False


class UserHistoryResponse(BaseModel):
    user: UserOut
    attempts: int
    history: list[HistoryItem]


class ClassSummaryResponse(BaseModel):
    school_class: str
    students_tested: int
    tests_completed: int
    # категория профессии → сколько раз встретилась в рекомендациях класса
    category_distribution: dict[str, int] = Field(default_factory=dict)
    top_professions: list[dict[str, int | str]] = Field(default_factory=list)
    # средний балл по классу: тип Голланда → значение
    average_interests: dict[str, float] = Field(default_factory=dict)
    average_softskills: dict[str, float] = Field(default_factory=dict)
    # предметы с самым низким средним knowledge_score — куда смотреть педагогу
    weakest_subjects: list[dict[str, float | str]] = Field(default_factory=list)
