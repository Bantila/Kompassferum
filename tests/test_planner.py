"""Подбор предметов для блока B.

Смысл подбора — не спрашивать все 13 предметов. Проверяем, что план всегда
получается полным и коротким, что правильные ответы не уезжают вместе с
вопросами и что разным складам достаются разные предметы: иначе сокращение
теста было бы просто выбрасыванием случайных вопросов.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.services import test_planner
from app.services.test_planner import (
    SUBJECTS_IN_PLAN,
    SubjectChoice,
    SubjectPlan,
    fallback_plan,
    plan_subjects,
    questions_for_plan,
)

ТЕХНАРЬ = {
    "investigative": 4.8, "realistic": 4.2, "conventional": 3.0,
    "social": 2.5, "artistic": 2.0, "enterprising": 1.8,
}
ГУМАНИТАРИЙ = {
    "artistic": 4.9, "social": 4.5, "enterprising": 3.0,
    "investigative": 2.2, "conventional": 2.0, "realistic": 1.5,
}


@pytest.fixture
def без_модели(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "ai_provider", "none")


@pytest.fixture
def с_моделью(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_provider", "gigachat")
    monkeypatch.setattr(settings, "gigachat_credentials", "test-key")
    monkeypatch.setattr(settings, "gigachat_model", "GigaChat")


def подмена_модели(monkeypatch: pytest.MonkeyPatch, предметы: list[str] | None = None,
                   error: Exception | None = None) -> None:
    """Подменяет запрос к модели. Возвращает то же, что настоящая функция:
    список кодов предметов после снятия дублей."""
    async def ask(interests):  # noqa: ANN001, ANN202
        if error is not None:
            raise error
        # проверяем заодно, что коды проходят схему — выдуманный предмет её не пройдёт
        план = SubjectPlan(subjects=[SubjectChoice(subject=s, reason="потому что") for s in предметы])
        уникальные: list[str] = []
        for choice in план.subjects:
            if choice.subject not in уникальные:
                уникальные.append(choice.subject)
        return уникальные

    monkeypatch.setattr(test_planner, "_ask_gigachat", ask)


async def test_plan_is_always_five_subjects(без_модели) -> None:
    план = await plan_subjects(ТЕХНАРЬ)

    assert len(план["subjects"]) == SUBJECTS_IN_PLAN
    assert len(set(план["subjects"])) == SUBJECTS_IN_PLAN, "предметы не должны повторяться"


async def test_plan_gives_exactly_fifteen_questions(без_модели) -> None:
    """Ради этого всё и затевалось: 15 вопросов вместо 52."""
    план = await plan_subjects(ТЕХНАРЬ)
    вопросы = questions_for_plan(план["subjects"])

    assert len(вопросы) == 15
    assert sum(q["type"] == "knowledge" for q in вопросы) == 10
    assert sum(q["type"] == "interest" for q in вопросы) == 5


async def test_plan_never_leaks_correct_answers(без_модели) -> None:
    план = await plan_subjects(ТЕХНАРЬ)

    assert not any("correct_index" in q for q in questions_for_plan(план["subjects"]))


async def test_different_profiles_get_different_subjects(без_модели) -> None:
    """Технарю и гуманитарию не должны достаться одни и те же предметы."""
    технарь = set((await plan_subjects(ТЕХНАРЬ))["subjects"])
    гуманитарий = set((await plan_subjects(ГУМАНИТАРИЙ))["subjects"])

    assert not технарь & гуманитарий


async def test_empty_profile_still_gets_a_plan(без_модели) -> None:
    """Пустой профиль не должен подвешивать тест."""
    план = await plan_subjects({})

    assert len(план["subjects"]) == SUBJECTS_IN_PLAN


async def test_model_choice_is_used(monkeypatch: pytest.MonkeyPatch, с_моделью) -> None:
    выбор = ["chemistry", "biology", "geography", "history", "literature"]
    подмена_модели(monkeypatch, предметы=выбор)

    план = await plan_subjects(ТЕХНАРЬ)

    assert план["subjects"] == выбор
    assert план["planned_by_model"] is True
    assert план["source"] == "GigaChat"


async def test_model_failure_falls_back_to_rules(monkeypatch: pytest.MonkeyPatch, с_моделью) -> None:
    """Отказ модели не должен оставлять ученика без теста."""
    подмена_модели(monkeypatch, error=RuntimeError("Unauthorized"))

    план = await plan_subjects(ТЕХНАРЬ)

    assert len(план["subjects"]) == SUBJECTS_IN_PLAN
    assert план["planned_by_model"] is False
    assert план["source"] == "fallback:rules"


async def test_model_duplicates_are_topped_up(monkeypatch: pytest.MonkeyPatch, с_моделью) -> None:
    """Схема допускает повтор предмета — иначе тест выродится в один предмет."""
    подмена_модели(monkeypatch, предметы=["physics", "physics", "physics", "physics", "physics"])

    план = await plan_subjects(ТЕХНАРЬ)

    assert len(set(план["subjects"])) == SUBJECTS_IN_PLAN
    assert план["source"].endswith("+rules"), "источник должен честно говорить о доборе"


def test_fallback_favours_leading_type() -> None:
    """Ведущий тип должен давать больше половины списка, иначе профили сольются."""
    предметы = fallback_plan(ТЕХНАРЬ)
    от_ведущего = set(test_planner.SUBJECTS_BY_TYPE["investigative"])

    assert len(set(предметы) & от_ведущего) >= 3


async def test_plan_endpoint_returns_questions_and_optional_subjects(client) -> None:
    """Эндпоинт отдаёт и план, и то, что можно допройти по желанию."""
    ответы = {f"a{i}": 5 if i in (3, 4) else 2 for i in range(1, 13)}

    response = await client.post("/api/tests/plan", json={"answers": ответы})

    assert response.status_code == 200
    данные = response.json()
    assert len(данные["subjects"]) == SUBJECTS_IN_PLAN
    assert len(данные["questions"]) == 15
    assert len(данные["optional_subjects"]) == 13 - SUBJECTS_IN_PLAN
    assert all(q.get("options") or q["type"] == "interest" for q in данные["questions"])


async def test_plan_endpoint_rejects_broken_answers(client) -> None:
    response = await client.post("/api/tests/plan", json={"answers": {"a1": 99}})

    assert response.status_code == 422
