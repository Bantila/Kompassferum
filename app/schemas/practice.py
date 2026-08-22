"""Схемы тренажёра задач."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TaskOut(BaseModel):
    id: str
    subject: str
    topic: str
    difficulty: str
    question: str
    hint: str = ""


class PackResponse(BaseModel):
    tasks: list[TaskOut]
    # предметы, по которым собран пак, и откуда они взялись
    subjects: list[str]
    reason: str


class AnswerRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=16)
    answer: str = Field(max_length=500)


class AchievementOut(BaseModel):
    code: str
    icon: str
    title: str
    hint: str
    rarity: str
    earned: bool = True


class AnswerResponse(BaseModel):
    is_correct: bool
    correct_answer: str
    explanation: str
    error_type: str
    error_label: str
    recommendation: str
    confidence: float
    # разбор от ИИ; None — когда ИИ недоступен, тогда хватает recommendation
    ai_explanation: str | None = None
    # геймификация: что ученик получил за этот ответ
    xp_earned: int = 0
    xp_total: int = 0
    level: int = 1
    level_up: bool = False
    streak_days: int = 0
    new_achievements: list[AchievementOut] = Field(default_factory=list)


class ProgressResponse(BaseModel):
    level: int
    xp: int
    xp_in_level: int
    xp_to_next: int
    xp_per_level: int
    streak_days: int
    best_streak: int
    total_tasks: int
    correct_tasks: int
    accuracy: float
    achievements: list[AchievementOut]
    earned_count: int
    total_achievements: int


class SubjectStat(BaseModel):
    subject: str
    total: int
    correct: int
    accuracy: float


class PracticeStatsResponse(BaseModel):
    total_answered: int
    total_correct: int
    accuracy: float
    by_subject: list[SubjectStat]
    # тип ошибки → сколько раз встретился: видно, на чём ученик спотыкается
    error_breakdown: dict[str, int]
