"""Подбор профессий через GigaChat со строгой схемой ответа.

Сеть не трогаем: клиент подменяется целиком. Главное отличие от OpenRouter —
формат держится не на тексте промпта, а на JSON-схеме, которую проверяет сам
API. Поэтому здесь проверяется не разбор текста, а что схема требует ровно
пять профессий с категорией из перечня, и что любой отказ Сбера по-прежнему
приводит к rule-based подбору, а не к исключению.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.services import ai_recommender
from app.services.ai_recommender import (
    FALLBACK_MODEL_NAME,
    ProfessionAdvice,
    ProfessionSuggestion,
    recommend_professions,
)

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


def подсказка(номер: int) -> ProfessionSuggestion:
    return ProfessionSuggestion(
        name=f"Профессия {номер}",
        reasoning="Твой investigative 4.8 и знание математики 5.0 говорят сами за себя.",
        subjects_to_improve=["информатика"],
        category="технологии",
    )


ADVICE = ProfessionAdvice(professions=[подсказка(i) for i in range(5)])


@pytest.fixture
def gigachat_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_provider", "gigachat")
    monkeypatch.setattr(settings, "gigachat_credentials", "test-authorization-key")
    monkeypatch.setattr(settings, "gigachat_model", "GigaChat")


class FakeStructured:
    """Модель с наложенной схемой: возвращает готовый объект, а не текст."""

    def __init__(self, advice: ProfessionAdvice | None, error: Exception | None) -> None:
        self.advice, self.error = advice, error
        self.calls: list = []

    async def ainvoke(self, messages):  # noqa: ANN001, ANN202
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return self.advice


def fake_gigachat(
    monkeypatch: pytest.MonkeyPatch,
    *,
    advice: ProfessionAdvice | None = ADVICE,
    error: Exception | None = None,
) -> dict:
    """Подменяет langchain_gigachat.GigaChat, сохраняя параметры вызова."""
    записано: dict = {}
    structured = FakeStructured(advice, error)

    class FakeModel:
        def __init__(self, **kwargs):
            записано["client"] = kwargs

        def with_structured_output(self, schema, **kwargs):  # noqa: ANN001, ANN202
            записано["schema"] = schema
            записано["structured_kwargs"] = kwargs
            return structured

    import langchain_gigachat

    monkeypatch.setattr(langchain_gigachat, "GigaChat", FakeModel)
    записано["structured"] = structured
    return записано


async def test_answer_by_schema_is_used(
    monkeypatch: pytest.MonkeyPatch, gigachat_selected
) -> None:
    записано = fake_gigachat(monkeypatch)

    result = await recommend_professions(SCORES)

    assert result["fallback"] is False
    assert result["model_used"] == "GigaChat"
    assert [p["name"] for p in result["professions"]] == [f"Профессия {i}" for i in range(5)]


async def test_schema_is_sent_to_api(monkeypatch: pytest.MonkeyPatch, gigachat_selected) -> None:
    """Строгость должна держаться на API, а не на просьбе в промпте."""
    записано = fake_gigachat(monkeypatch)

    await recommend_professions(SCORES)

    assert записано["schema"] is ProfessionAdvice
    assert записано["structured_kwargs"] == {"method": "json_schema", "strict": True}
    assert записано["client"]["credentials"] == "test-authorization-key"
    assert записано["client"]["scope"] == "GIGACHAT_API_PERS"
    assert записано["client"]["base_url"] == "https://api.giga.chat/v1"


async def test_prompt_has_no_json_instructions(
    monkeypatch: pytest.MonkeyPatch, gigachat_selected
) -> None:
    """Просить «верни валидный JSON» бессмысленно, когда формат гарантирован."""
    записано = fake_gigachat(monkeypatch)

    await recommend_professions(SCORES)

    системное, пользовательское = записано["structured"].calls[0]
    # слово JSON в описании входных данных допустимо, а вот требований
    # к формату ответа быть не должно — за них отвечает схема
    assert ai_recommender.JSON_FORMAT_TAIL not in системное.content
    assert "```" not in системное.content
    assert "СТРОГО валидным" not in системное.content
    # профиль уходит в модель целиком, иначе обосновать баллами нечем
    assert json.loads(пользовательское.content) == SCORES


@pytest.mark.parametrize(
    ("error", "случай"),
    [
        (RuntimeError("Unauthorized"), "ключ не принят"),
        (TimeoutError("too slow"), "сервис не ответил"),
        (ValueError("500 Internal Server Error"), "ошибка на стороне Сбера"),
    ],
)
async def test_any_failure_falls_back(
    monkeypatch: pytest.MonkeyPatch, gigachat_selected, error: Exception, случай: str
) -> None:
    fake_gigachat(monkeypatch, advice=None, error=error)

    result = await recommend_professions(SCORES)

    assert result["fallback"] is True, случай
    assert result["model_used"] == FALLBACK_MODEL_NAME
    assert len(result["professions"]) == 5


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


@pytest.mark.parametrize(
    ("сколько", "случай"),
    [(4, "меньше пяти"), (6, "больше пяти")],
)
def test_schema_requires_exactly_five(сколько: int, случай: str) -> None:
    with pytest.raises(ValidationError):
        ProfessionAdvice(professions=[подсказка(i) for i in range(сколько)])


def test_schema_rejects_unknown_category() -> None:
    """Категория нужна фронту для цвета карточки — выдуманная сломает вид."""
    with pytest.raises(ValidationError):
        ProfessionSuggestion(
            name="Космонавт",
            reasoning="потому что",
            subjects_to_improve=["физика"],
            category="приключения",
        )
