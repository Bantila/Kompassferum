"""Импорт всех моделей — нужен, чтобы Alembic видел их в Base.metadata."""

from app.models.recommendation import Recommendation
from app.models.test_result import TestResult
from app.models.user import User, UserRole

__all__ = ["Recommendation", "TestResult", "User", "UserRole"]
