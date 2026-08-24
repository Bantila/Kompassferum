"""Подбор профессий через GigaChat.

Сеть не трогаем: SDK подменяется целиком. Проверяем, что провайдер
выбирается настройкой, ответ разбирается тем же кодом, что и у OpenRouter,
а любой отказ Сбера приводит к rule-based подбору, а не к исключению.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.config import get_settings
from app.services import ai_recommender
from app.services.ai_recommender import FALLBACK_MODEL_NAME, recommend_professions

SCORES = {
    "interests": {"investigative": 4.8, "artistic": 2.0, "social": 3.0},
    "subjects": {
        "mathematics": {
            "correct_count": 3,
            "total_questions": 3,
            "knowledge_score": 5.0,
            "interest": 4.0,
            "subject_score": 4.65,
        }
    },
    "softskills": {"analytical": 4.6},
}

ANSWER = {
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


@pytest.fixture
def gigachat_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_provider", "gigachat")
    monkeypatch.setattr(settings, "gigachat_credentials", "test-authorization-key")
    monkeypatch.setattr(settings, "gigachat_model", "GigaChat")


def fake_sdk(monkeypatch: pytest.MonkeyPatch, *, content: str | None = None,
             error: Exception | None = None) -> dict:
    """Подменяет _ask_gigachat, сохраняя переданный промпт для проверок."""
    captured: dict = {}

    async def ask(scores):  # noqa: ANN001, ANN202
        captured["scores"] = scores
        if error is not None:
            raise error
        return content, {"choices": [{"message": {"content": content}}]}

    monkeypatch.setattr(ai_recommender, "_ask_gigachat", ask)
    return captured


async def test_gigachat_answer_is_used(monkeypatch: pytest.MonkeyPatch, gigachat_selected) -> None:
    captured = fake_sdk(monkeypatch, content=json.dumps(ANSWER, ensure_ascii=False))

    result = await recommend_professions(SCORES)

    assert result["fallback"] is False
    assert result["model_used"] == "GigaChat"
    assert len(result["professions"]) == 5
    # профиль ученика уходит в модель целиком, иначе обосновать баллами нечем
    assert captured["scores"] == SCORES


async def test_gigachat_markdown_wrapper_is_stripped(
    monkeypatch: pytest.MonkeyPatch, gigachat_selected
) -> None:
    """Модель часто отвечает пояснением и ```json — разбор это переживает."""
    fenced = "Вот подборка:\n```json\n" + json.dumps(ANSWER, ensure_ascii=False) + "\n```"
    fake_sdk(monkeypatch, content=fenced)

    result = await recommend_professions(SCORES)

    assert result["fallback"] is False
    assert len(result["professions"]) == 5


@pytest.mark.parametrize(
    ("error", "случай"),
    [
        (RuntimeError("Unauthorized"), "ключ не принят"),
        (TimeoutError("too slow"), "сервис не ответил"),
        (ValueError("500 Internal Server Error"), "ошибка на стороне сбера"),
    ],
)
async def test_any_gigachat_failure_falls_back(
    monkeypatch: pytest.MonkeyPatch, gigachat_selected, error: Exception, случай: str
) -> None:
    fake_sdk(monkeypatch, error=error)

    result = await recommend_professions(SCORES)

    assert result["fallback"] is True, случай
    assert result["model_used"] == FALLBACK_MODEL_NAME
    assert len(result["professions"]) == 5


async def test_gigachat_nonsense_answer_falls_back(
    monkeypatch: pytest.MonkeyPatch, gigachat_selected
) -> None:
    fake_sdk(monkeypatch, content="Извините, не могу ответить на этот вопрос.")

    result = await recommend_professions(SCORES)

    assert result["fallback"] is True


async def test_provider_without_credentials_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """AI_PROVIDER=gigachat без ключа не должен ронять подбор."""
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_provider", "gigachat")
    monkeypatch.setattr(settings, "gigachat_credentials", "")

    async def explode(scores):  # noqa: ANN001, ANN202
        raise AssertionError("без ключа запроса быть не должно")

    monkeypatch.setattr(ai_recommender, "_ask_gigachat", explode)

    result = await recommend_professions(SCORES)

    assert result["fallback"] is True
    assert result["model_used"] == FALLBACK_MODEL_NAME


def test_provider_choice_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ключ от одного провайдера не должен включать другого."""
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_provider", "none")
    monkeypatch.setattr(settings, "gigachat_credentials", "key")
    monkeypatch.setattr(settings, "openrouter_api_key", "key")

    assert ai_recommender._select_provider() is None


async def test_gigachat_request_shape(monkeypatch: pytest.MonkeyPatch, gigachat_selected) -> None:
    """Проверяем сам вызов SDK: модель, температура и роли сообщений."""
    sent: dict = {}

    class FakeClient:
        def __init__(self, **kwargs):
            sent["client"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def achat(self, chat):  # noqa: ANN001, ANN202
            sent["chat"] = chat
            message = SimpleNamespace(content=json.dumps(ANSWER, ensure_ascii=False))
            response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
            response.dict = lambda: {"ok": True}
            return response

    import gigachat

    monkeypatch.setattr(gigachat, "GigaChat", FakeClient)

    result = await recommend_professions(SCORES)

    assert result["fallback"] is False
    assert sent["client"]["credentials"] == "test-authorization-key"
    assert sent["client"]["scope"] == "GIGACHAT_API_PERS"
    assert sent["client"]["base_url"] == "https://api.giga.chat/v1"
    assert sent["chat"].model == "GigaChat"
    assert sent["chat"].temperature == 0.3
    assert [m.role for m in sent["chat"].messages] == ["system", "user"]
