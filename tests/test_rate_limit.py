"""Ограничение частоты запросов.

Смысл лимита — закрыть две дыры: перебор пароля педагога и забивание базы
прохождениями. Проверяем, что лимит срабатывает, что его нельзя обойти
подменой заголовка, что он не задевает обычную работу класса и что окно
действительно скользящее, а не вечная блокировка.
"""

from __future__ import annotations

import pytest

from app.services import rate_limit

ВХОД = {"email": "kto-to@example.com", "password": "неверный-пароль"}


async def _вход(client, ip: str = "10.0.0.1"):
    return await client.post("/api/auth/login", json=ВХОД, headers={"X-Real-IP": ip})


async def test_password_guessing_is_cut_off(client) -> None:
    """Одиннадцатая попытка входа подряд должна упереться в лимит."""
    коды = [(await _вход(client)).status_code for _ in range(11)]

    assert коды[:10] == [401] * 10, "до лимита должен работать обычный отказ"
    assert коды[10] == 429


async def test_limit_response_says_when_to_retry(client) -> None:
    """429 без Retry-After оставляет клиента гадать, когда повторить."""
    for _ in range(10):
        await _вход(client)

    ответ = await _вход(client)

    assert ответ.status_code == 429
    assert int(ответ.headers["Retry-After"]) > 0


async def test_limit_is_per_address(client) -> None:
    """Исчерпанный лимит одного адреса не должен закрывать вход всем остальным."""
    for _ in range(11):
        await _вход(client, ip="10.0.0.1")

    сосед = await _вход(client, ip="10.0.0.2")

    assert сосед.status_code == 401, "чужой адрес не должен страдать от соседа"


async def test_forwarded_for_cannot_buy_extra_attempts(client) -> None:
    """X-Forwarded-For клиент дописывает сам — подмена не должна сбрасывать счёт.

    Если бы ключ брался оттуда, перебор пароля обходился бы новым значением
    заголовка на каждый запрос, и лимит не значил бы ничего.
    """
    for i in range(10):
        await client.post(
            "/api/auth/login",
            json=ВХОД,
            headers={"X-Real-IP": "10.0.0.7", "X-Forwarded-For": f"1.2.3.{i}"},
        )

    ответ = await client.post(
        "/api/auth/login",
        json=ВХОД,
        headers={"X-Real-IP": "10.0.0.7", "X-Forwarded-For": "9.9.9.9"},
    )

    assert ответ.status_code == 429


async def test_whole_classroom_can_enter_at_once(client) -> None:
    """Класс сидит за одним NAT и открывает приложение одновременно.

    Лимит на вход в мини-приложение обязан вмещать кабинет целиком, иначе
    половина урока не войдёт — это хуже, чем отсутствие лимита.
    """
    коды = set()
    for _ in range(30):
        ответ = await client.post(
            "/api/auth/miniapp",
            json={"init_data": "мусор", "platform": "telegram"},
            headers={"X-Real-IP": "192.168.1.1"},
        )
        коды.add(ответ.status_code)

    assert 429 not in коды


async def test_window_slides(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """Лимит — окно, а не вечный бан: через минуту вход снова открыт."""
    for _ in range(11):
        await _вход(client)
    assert (await _вход(client)).status_code == 429

    настоящее = rate_limit.time.monotonic
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: настоящее() + 61)

    assert (await _вход(client)).status_code == 401


def test_reset_clears_counters() -> None:
    """Без сброса счётчик протекал бы между тестами."""
    rate_limit._попадания["проба:1.1.1.1"].append(rate_limit.time.monotonic())

    rate_limit.reset()

    assert not rate_limit._попадания


async def test_submit_survives_a_class_but_not_a_script(client, full_answers) -> None:
    """Тридцать сдач с адреса проходят, поток в тысячи — нет."""
    тело = {
        "max_user_id": "flood_1",
        "full_name": "Ученик",
        "school_class": "7Б",
        "role": "student",
        "answers": full_answers,
    }
    коды = []
    for i in range(45):
        тело["max_user_id"] = f"flood_{i}"
        ответ = await client.post("/api/tests/submit", json=тело, headers={"X-Real-IP": "203.0.113.5"})
        коды.append(ответ.status_code)

    assert 429 not in коды[:30], "класс должен сдать тест без препятствий"
    assert коды[-1] == 429, "бесконечный поток обязан упереться в потолок"
