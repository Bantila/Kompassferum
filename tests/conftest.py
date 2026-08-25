"""Общие фикстуры.

БД для тестов — SQLite (aiosqlite), файл во временной директории. Она нужна
только здесь: боевой стек работает на PostgreSQL. Так тесты не требуют
поднятого postgres-контейнера и проходят быстро в CI.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_DB_FILE = Path(tempfile.gettempdir()) / "kompas_pytest.db"
_DB_FILE.unlink(missing_ok=True)

# Переменные окружения выставляются ДО импорта app: engine и Settings
# создаются на импорте модуля и кэшируются.
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_FILE.as_posix()}"
os.environ["AI_PROVIDER"] = "openrouter"
os.environ["OPENROUTER_API_KEY"] = "test-key"
os.environ["OPENROUTER_MODEL"] = "moonshotai/kimi-k2"
os.environ["MAX_WEBHOOK_SECRET"] = "test-secret"

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _чистый_счётчик_лимитов():
    """Счётчик частоты живёт в памяти процесса — между тестами его надо обнулять.

    Иначе тест, отправивший десяток запросов, оставляет соседям исчерпанный
    лимит, и падает не он, а следующий за ним.
    """
    from app.services import rate_limit

    rate_limit.reset()
    yield
    rate_limit.reset()


@pytest.fixture
async def client() -> AsyncClient:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
def согласившийся(client):
    """Фабрика: ученик с записанным согласием на обработку данных.

    Без согласия /submit отвечает 403 — это данные ребёнка. В жизни ученик
    входит через мессенджер и принимает документ до теста; тесты сдают его
    напрямую, поэтому пользователя и согласие заводим заранее.
    """
    from app.database import SessionLocal
    from app.models import User, UserRole
    from app.services import consent

    async def создать(max_user_id: str, **поля):
        async with SessionLocal() as session:
            user = User(max_user_id=max_user_id, role=UserRole.student, **поля)
            session.add(user)
            await session.flush()
            await consent.grant(session, user.id)
            await session.commit()
            return user.id

    return создать


@pytest.fixture
def full_answers() -> dict:
    """Ответы на весь тест: сильный «исследователь» с хорошей математикой."""
    from app.services.test_scoring import load_questions

    data = load_questions()
    answers: dict = {}
    for question in data["block_a_interests"]:
        answers[question["id"]] = 5 if question["type"] == "investigative" else 2
    for question in data["block_b_subjects"]:
        if question["type"] == "knowledge":
            # на математике отвечаем верно, на остальном — первым вариантом
            answers[question["id"]] = (
                question["correct_index"] if question["subject"] == "mathematics" else 0
            )
        else:
            answers[question["id"]] = 4
    for question in data["block_c_softskills"]:
        answers[question["id"]] = 4
    return answers
