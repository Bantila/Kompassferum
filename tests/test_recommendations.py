"""Тесты подбора профессий. Реальный OpenRouter не дёргаем — httpx замокан."""

from __future__ import annotations

import json

import httpx
import pytest

from app.services import ai_recommender
from app.services.ai_recommender import (
    FALLBACK_MODEL_NAME,
    build_fallback,
    recommend_professions,
)

SCORES = {
    "interests": {
        "realistic": 2.0,
        "investigative": 4.8,
        "artistic": 2.5,
        "social": 3.0,
        "enterprising": 1.5,
        "conventional": 3.5,
    },
    "subjects": {
        "mathematics": {
            "correct_count": 3,
            "total_questions": 3,
            "knowledge_score": 5.0,
            "interest": 4.0,
            "subject_score": 4.65,
        }
    },
    "softskills": {"analytical": 4.6, "teamwork": 3.0},
}

LLM_PAYLOAD = {
    "professions": [
        {
            "name": f"Профессия {i}",
            "reasoning": "Твой investigative 4.8 и знание математики 5.0 говорят сами за себя.",
            "subjects_to_improve": ["информатика"],
            "category": "технологии",
        }
        for i in range(5)
    ]
}


def _mock_post(monkeypatch, *, content: str | None = None, exc: Exception | None = None,
               status_code: int = 200) -> None:
    """Подменяет запросы к OpenRouter — до сети дело не доходит.

    Перехватываем только вызовы на openrouter.ai: тестовый ASGI-клиент ходит
    в наше же приложение тем же httpx и должен работать по-настоящему.
    """
    original_post = httpx.AsyncClient.post

    async def fake_post(self, url, **kwargs):  # noqa: ANN001, ANN202
        if "openrouter.ai" not in str(url):
            return await original_post(self, url, **kwargs)
        if exc is not None:
            raise exc
        request = httpx.Request("POST", url)
        body = {"choices": [{"message": {"content": content}}]} if content else {"error": "boom"}
        return httpx.Response(status_code, json=body, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)


async def test_successful_llm_response(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_post(monkeypatch, content=json.dumps(LLM_PAYLOAD, ensure_ascii=False))

    result = await recommend_professions(SCORES)

    assert result["fallback"] is False
    assert result["model_used"] == "moonshotai/kimi-k2"
    assert len(result["professions"]) == 5
    assert result["professions"][0]["name"] == "Профессия 0"
    assert result["professions"][0]["category"] == "технологии"


async def test_markdown_fenced_json_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Модель часто оборачивает ответ в ```json — это не должно ломать разбор."""
    fenced = "Вот результат:\n```json\n" + json.dumps(LLM_PAYLOAD, ensure_ascii=False) + "\n```"
    _mock_post(monkeypatch, content=fenced)

    result = await recommend_professions(SCORES)

    assert result["fallback"] is False
    assert len(result["professions"]) == 5


@pytest.mark.parametrize(
    ("kwargs", "case"),
    [
        ({"exc": httpx.TimeoutException("too slow")}, "таймаут"),
        ({"exc": httpx.ConnectError("no route")}, "сеть недоступна"),
        ({"status_code": 500, "content": None}, "500 от OpenRouter"),
        ({"content": "я не умею в JSON"}, "не-JSON в ответе"),
        ({"content": '{"professions": []}'}, "пустой список профессий"),
        ({"content": '{"professions": [{"reasoning": "без имени"}]}'}, "профессия без name"),
    ],
)
async def test_any_llm_failure_falls_back(
    monkeypatch: pytest.MonkeyPatch, kwargs: dict, case: str
) -> None:
    _mock_post(monkeypatch, **kwargs)

    result = await recommend_professions(SCORES)

    assert result["fallback"] is True, case
    assert result["model_used"] == FALLBACK_MODEL_NAME
    assert len(result["professions"]) == 5


async def test_missing_api_key_falls_back_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ai_recommender.get_settings(), "openrouter_api_key", "")

    original_post = httpx.AsyncClient.post

    async def explode(self, url, **kwargs):  # noqa: ANN001, ANN202
        if "openrouter.ai" in str(url):
            raise AssertionError("без ключа сетевого запроса быть не должно")
        return await original_post(self, url, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", explode)

    result = await recommend_professions(SCORES)

    assert result["fallback"] is True
    assert result["model_used"] == FALLBACK_MODEL_NAME


def test_fallback_follows_top_holland_type() -> None:
    result = build_fallback(SCORES)
    assert result["top_interest"] == "investigative"
    assert "Программист" in {p["name"] for p in result["professions"]}

    creative = build_fallback({"interests": {"artistic": 4.9, "social": 2.0}})
    assert creative["top_interest"] == "artistic"
    assert all(p["reasoning"] for p in creative["professions"])


def test_fallback_survives_empty_profile() -> None:
    result = build_fallback({})
    assert len(result["professions"]) == 5
    assert result["fallback"] is True


async def _токен(max_user_id: str) -> dict:
    """Заголовок владельца данных: история и рекомендации отдаются только ему."""
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import User
    from app.services.security import create_access_token

    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.max_user_id == max_user_id))
        return {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def test_submit_stores_and_returns_recommendations(
    client, monkeypatch: pytest.MonkeyPatch, full_answers: dict, согласившийся
) -> None:
    """Сквозной путь: приём ответов → сохранение → выдача по id и в истории."""
    await согласившийся("max_42")
    _mock_post(monkeypatch, content=json.dumps(LLM_PAYLOAD, ensure_ascii=False))

    response = await client.post(
        "/api/tests/submit",
        json={"max_user_id": "max_42", "answers": full_answers, "school_class": "7Б"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["fallback"] is False
    assert data["progress"]["is_complete"] is True
    assert data["computed_scores"]["subjects"]["mathematics"]["knowledge_score"] == 5.0
    assert len(data["recommendations"]) == 5

    свои = await _токен("max_42")
    saved = await client.get(f"/api/recommendations/{data['test_result_id']}", headers=свои)
    assert saved.status_code == 200
    assert [p["name"] for p in saved.json()["professions"]] == [
        p["name"] for p in data["recommendations"]
    ]

    history = await client.get("/api/users/max_42/history", headers=свои)
    assert history.status_code == 200
    assert history.json()["attempts"] == 1
    assert history.json()["history"][0]["top_interests"][0] == "investigative"


async def test_unknown_recommendation_returns_404(client, full_answers, согласившийся) -> None:
    await согласившийся("kto_to")
    await client.post("/api/tests/submit", json={"max_user_id": "kto_to", "answers": full_answers})
    свои = await _токен("kto_to")

    response = await client.get(
        "/api/recommendations/00000000-0000-0000-0000-000000000000", headers=свои
    )

    assert response.status_code == 404


async def test_frontend_is_served(client) -> None:
    """Мини-приложение отдаётся с того же origin, что и API."""
    page = await client.get("/")
    assert page.status_code == 200
    assert "<div class=\"phone\">" in page.text

    script = await client.get("/static/app.js")
    assert script.status_code == 200
    assert "kompas_state_v1" in script.text
