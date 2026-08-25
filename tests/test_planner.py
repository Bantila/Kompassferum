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
from app.services.test_scoring import load_questions
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


# --- Ротация сложностей между попытками -------------------------------------
#
# До этого пара сложностей была прибита гвоздями к ("easy", "hard"): повторное
# прохождение состояло из тех же задач, а 13 средних вопросов банка не
# задавались никогда.


def test_first_attempt_keeps_previous_difficulties() -> None:
    """Первая попытка не должна измениться — для большинства учеников тест прежний."""
    assert test_planner.difficulties_for_attempt(0) == ("easy", "hard")


def test_repeat_attempts_get_different_tasks(без_модели) -> None:
    """Второй заход не должен состоять из тех же задач, что первый."""
    предметы = ["physics", "mathematics", "informatics", "biology", "chemistry"]

    первая = {q["id"] for q in questions_for_plan(предметы, attempt=0)}
    вторая = {q["id"] for q in questions_for_plan(предметы, attempt=1)}

    assert первая != вторая, "повторное прохождение обязано отличаться"
    assert первая & вторая, "полная смена задач — потеряется преемственность оценки"


def test_medium_questions_are_actually_asked() -> None:
    """Ради этого всё и затевалось: средние вопросы больше не мёртвый груз."""
    предметы = ["physics", "mathematics", "informatics", "biology", "chemistry"]
    банк = {q["id"]: q for q in load_questions()["block_b_subjects"]}

    сложности = set()
    for попытка in range(len(test_planner.DIFFICULTY_ROTATION)):
        for q in questions_for_plan(предметы, attempt=попытка):
            if q["type"] == "knowledge":
                сложности.add(банк[q["id"]]["difficulty"])

    assert сложности == {"easy", "medium", "hard"}


def test_difficulty_is_uniform_within_one_attempt() -> None:
    """Внутри прохождения пара одна на все предметы.

    Балл предмета — доля верных ответов, сложность в него не входит. Разные
    пары у разных предметов сделали бы предметы несравнимыми, а именно на их
    сравнении строится совет, что подтягивать.
    """
    предметы = ["physics", "literature", "history", "biology", "chemistry"]
    банк = {q["id"]: q for q in load_questions()["block_b_subjects"]}

    for попытка in range(6):
        по_предметам: dict[str, set[str]] = {}
        for q in questions_for_plan(предметы, attempt=попытка):
            if q["type"] == "knowledge":
                по_предметам.setdefault(q["subject"], set()).add(банк[q["id"]]["difficulty"])
        наборы = set(map(frozenset, по_предметам.values()))
        assert len(наборы) == 1, f"попытка {попытка}: предметам достались разные сложности"


def test_rotation_wraps_around_and_survives_junk() -> None:
    """Номер попытки приходит из базы — он не должен ронять подбор."""
    длина = len(test_planner.DIFFICULTY_ROTATION)

    assert test_planner.difficulties_for_attempt(длина) == test_planner.difficulties_for_attempt(0)
    assert test_planner.difficulties_for_attempt(-5) == test_planner.difficulties_for_attempt(0)


def test_every_attempt_still_gives_fifteen_questions() -> None:
    """Сокращение теста не должно ломаться ни на какой попытке."""
    предметы = ["physics", "mathematics", "informatics", "biology", "chemistry"]

    for попытка in range(6):
        вопросы = questions_for_plan(предметы, attempt=попытка)
        assert len(вопросы) == 15, f"попытка {попытка}"
        assert not any("correct_index" in q for q in вопросы)


async def test_plan_endpoint_works_without_login(client) -> None:
    """Демо-страница ходит на /plan без токена — это не должно падать."""
    ответы = {f"a{i}": 5 if i in (3, 4) else 2 for i in range(1, 13)}

    response = await client.post("/api/tests/plan", json={"answers": ответы})

    assert response.status_code == 200
    данные = response.json()
    assert данные["attempt"] == 0
    assert данные["difficulties"] == ["easy", "hard"]


async def test_plan_endpoint_ignores_broken_token(client) -> None:
    """Протухший токен не должен закрывать вход в тест — просто первая попытка."""
    ответы = {f"a{i}": 3 for i in range(1, 13)}

    response = await client.post(
        "/api/tests/plan",
        json={"answers": ответы},
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert response.status_code == 200
    assert response.json()["attempt"] == 0


# --- Сложность видна в результате ------------------------------------------
#
# Балл — доля верных ответов, сложность в него не входит. Значит падение между
# попытками может означать не «стал хуже», а «достались задачи потруднее».
# Формулу трогать нельзя: пример 2/3 -> 3.98 закреплён техзаданием. Поэтому
# делаем сложность видимой.


def test_asked_difficulties_reads_the_attempt() -> None:
    предметы = ["physics", "mathematics", "informatics", "biology", "chemistry"]

    было = [
        test_planner.asked_difficulties({q["id"]: 0 for q in questions_for_plan(предметы, attempt=n)})
        for n in range(3)
    ]

    assert было == [["easy", "hard"], ["medium", "hard"], ["easy", "medium"]]


def test_asked_difficulties_ignores_junk() -> None:
    """Ответы приходят из базы — там может лежать что угодно из прошлых версий."""
    assert test_planner.asked_difficulties({}) == []
    assert test_planner.asked_difficulties({"нет-такого": 3, "a1": 5}) == []
    assert test_planner.asked_difficulties("не словарь") == []


def test_difficulties_are_ordered_not_random() -> None:
    """Порядок фиксирован: иначе подпись в истории скачет между открытиями."""
    все = {q["id"]: 0 for q in load_questions()["block_b_subjects"] if q["type"] == "knowledge"}

    assert test_planner.asked_difficulties(все) == ["easy", "medium", "hard"]


async def test_submit_reports_difficulties(client, full_answers, согласившийся) -> None:
    await согласившийся("diff_1")
    ответ = await client.post(
        "/api/tests/submit", json={"max_user_id": "diff_1", "answers": full_answers}
    )

    assert ответ.status_code == 201
    assert ответ.json()["difficulties"] == ["easy", "medium", "hard"]


async def test_history_shows_difficulties(client, full_answers, согласившийся) -> None:
    """Ради этого всё и делалось: сравнивая прохождения, видно, чем они мерились."""
    await согласившийся("diff_2")
    await client.post(
        "/api/tests/submit", json={"max_user_id": "diff_2", "answers": full_answers}
    )

    история = await client.get("/api/users/diff_2/history")

    assert история.status_code == 200
    assert история.json()["history"][0]["difficulties"] == ["easy", "medium", "hard"]
