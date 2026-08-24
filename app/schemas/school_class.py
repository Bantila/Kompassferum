"""Схемы создания класса педагогом и присоединения ученика по коду."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class CreateClassRequest(BaseModel):
    name: str = Field(min_length=1, max_length=32, description="Например: 7Б")


class ClassOut(BaseModel):
    id: uuid.UUID
    name: str
    join_code: str
    students_count: int
    created_at: datetime


class JoinClassRequest(BaseModel):
    join_code: str = Field(min_length=4, max_length=8)


class JoinClassResponse(BaseModel):
    class_id: uuid.UUID
    class_name: str


class LeaderboardRow(BaseModel):
    rank: int
    student_id: uuid.UUID
    full_name: str
    level: int
    xp: int
    streak_days: int
    solved: int
    correct: int
    accuracy: float
    test_done: bool
    # пометка о доверии к последнему прохождению, если ответам верить не стоит
    integrity_note: str | None = None


class LeaderboardResponse(BaseModel):
    class_id: uuid.UUID
    class_name: str
    rows: list[LeaderboardRow]


class CreateAssignmentRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    subjects: list[str] = Field(default_factory=list, max_length=12)
    size: int = Field(default=5, ge=1, le=20)
    difficulty: str | None = Field(default=None, pattern="^(easy|medium|hard)$")
    due_date: date | None = None


class AssignmentOut(BaseModel):
    id: uuid.UUID
    title: str
    subjects: list[str]
    size: int
    difficulty: str | None = None
    due_date: date | None = None
    created_at: datetime
    # сколько учеников класса уже решили хотя бы часть задания
    completed_by: int = 0
    students_total: int = 0
