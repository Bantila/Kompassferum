"""Проверка доверия к ответам.

Главное требование — не мешать честному ученику: ложная пометка хуже
пропущенного прокликивания, потому что педагог перестанет верить пометкам
вообще. Поэтому проверяем обе стороны: что нормальное прохождение остаётся
чистым и что явное прокликивание видно.
"""

from __future__ import annotations

import pytest

from app.services.integrity import check, summary_line


def честное_прохождение() -> dict:
    """Разные оценки в шкалах, разные варианты в задачах, живое время."""
    ответы: dict = {"a1": 4, "a2": 2, "a3": 5, "a4": 3, "a5": 2, "a6": 4,
                    "a7": 3, "a8": 5, "a9": 2, "a10": 1, "a11": 4, "a12": 3}
    времена = [14.2, 41.0, 9.5, 33.1, 11.8, 25.4, 7.9, 18.3, 22.0, 12.6]
    for номер, секунды in enumerate(времена, start=1):
        ключ = f"b{номер}_k1"
        ответы[ключ] = {"selected_index": номер % 4, "time_spent_seconds": секунды}
    return ответы


def test_honest_run_is_not_flagged() -> None:
    результат = check(честное_прохождение())

    assert результат["trust"] == "high"
    assert результат["flags"] == []
    assert summary_line(результат) is None


def test_clicked_through_run_is_caught() -> None:
    """Один вариант везде, одна оценка в шкалах, доли секунды на задачу."""
    ответы: dict = {f"a{i}": 5 for i in range(1, 13)}
    for номер in range(1, 11):
        ответы[f"b{номер}_k1"] = {"selected_index": 0, "time_spent_seconds": 0.6}

    результат = check(ответы)

    assert результат["trust"] == "low"
    коды = {f["code"] for f in результат["flags"]}
    assert коды == {"rushed", "same_option", "straight_line"}
    assert summary_line(результат) == "Ответы похожи на случайные — результат стоит перепроверить"


def test_fast_but_varied_answers_are_only_a_warning() -> None:
    """Торопился, но отвечал по-разному — это подозрение, а не приговор."""
    ответы: dict = {"a1": 4, "a2": 2, "a3": 5, "a4": 3, "a5": 1,
                    "a6": 4, "a7": 3, "a8": 2, "a9": 5, "a10": 1}
    for номер in range(1, 9):
        ответы[f"b{номер}_k1"] = {"selected_index": номер % 4, "time_spent_seconds": 1.1}

    результат = check(ответы)

    assert результат["trust"] == "medium"
    assert {f["code"] for f in результат["flags"]} == {"rushed"}


def test_slow_thoughtful_answers_are_never_flagged() -> None:
    """Долгие ответы не должны попадать под подозрение ни при каких условиях."""
    ответы = {
        f"b{номер}_k1": {"selected_index": номер % 4, "time_spent_seconds": 60.0}
        for номер in range(1, 11)
    }

    assert check(ответы)["flags"] == []


def test_answers_without_timing_do_not_trigger_rush_flag() -> None:
    """Старые прохождения без времени не должны задним числом становиться подозрительными."""
    ответы = {f"b{номер}_k1": номер % 4 for номер in range(1, 11)}

    результат = check(ответы)

    assert not any(f["code"] == "rushed" for f in результат["flags"])


def test_empty_answers_give_unknown() -> None:
    результат = check({})

    assert результат["trust"] == "unknown"
    assert summary_line(результат) is None


def test_unknown_question_ids_are_ignored() -> None:
    """Мусор в ответах не должен ломать проверку."""
    assert check({"нет_такого": 5, "ещё_один": {"selected_index": 1}})["flags"] == []


@pytest.mark.parametrize("мало", [1, 4])
def test_too_few_answers_do_not_trigger_same_option(мало: int) -> None:
    """На двух-трёх задачах совпадение варианта — случайность, а не признак."""
    ответы = {
        f"b{номер}_k1": {"selected_index": 0, "time_spent_seconds": 30.0}
        for номер in range(1, мало + 1)
    }

    assert not any(f["code"] == "same_option" for f in check(ответы)["flags"])


async def test_submit_stores_integrity(client) -> None:
    """Оценка доверия должна сохраняться вместе с результатом теста."""
    ответы = {f"a{i}": 5 for i in range(1, 13)}
    ответы.update(
        {f"b{n}_k1": {"selected_index": 0, "time_spent_seconds": 0.5} for n in range(1, 11)}
    )

    response = await client.post(
        "/api/tests/submit", json={"max_user_id": "click_through", "answers": ответы}
    )

    assert response.status_code == 201

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import TestResult

    async with SessionLocal() as session:
        результат = (await session.scalars(select(TestResult))).all()[-1]

    assert результат.integrity["trust"] == "low"
    assert результат.integrity["flags"], "признаки должны сохраняться, а не только вердикт"
