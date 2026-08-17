"""Схемы рекомендаций."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProfessionOut(BaseModel):
    name: str
    reasoning: str = ""
    subjects_to_improve: list[str] = Field(default_factory=list)
    category: str = "не указана"


class RecommendationOut(BaseModel):
    id: uuid.UUID
    test_result_id: uuid.UUID
    professions: list[ProfessionOut]
    model_used: str
    # True — рекомендации собраны упрощённым rule-based алгоритмом, а не ИИ
    fallback: bool
    created_at: datetime
    computed_scores: dict[str, Any] | None = None
