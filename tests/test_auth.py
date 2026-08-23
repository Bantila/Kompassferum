"""Вход: у ученика единственный путь — подпись мессенджера.

Раньше один человек мог завести аккаунт на сайте и второй через Telegram —
это были разные записи с разным прогрессом. Регистрация по почте осталась
только для педагогов, поэтому дублей у ученика больше не возникает.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

TEACHER = {
    "email": "teacher@school.ru",
    "password": "very-secret",
    "full_name": "Ирина Петровна",
}


def telegram_init_data(user_id: int, token: str, first_name: str = "Артём") -> str:
    """Валидная initData Telegram — подписывается тем же ключом, что и в проде."""
    payload = {
        "auth_date": str(int(time.time())),
        "user": json.dumps(
            {"id": user_id, "first_name": first_name, "username": f"user{user_id}"},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    check_string = "\n".join(f"{k}={payload[k]}" for k in sorted(payload))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    payload["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(payload)


async def test_registration_always_creates_teacher(client) -> None:
    """Роль из запроса не принимается — иначе ученика снова заводили бы в обход бота."""
    response = await client.post("/api/auth/register", json={**TEACHER, "role": "student"})

    assert response.status_code == 201
    assert response.json()["user"]["role"] == "teacher"


async def test_registration_rejects_duplicate_email(client) -> None:
    assert (await client.post("/api/auth/register", json=TEACHER)).status_code == 201

    second = await client.post("/api/auth/register", json=TEACHER)

    assert second.status_code == 409


async def test_teacher_can_log_in_by_email(client) -> None:
    await client.post("/api/auth/register", json=TEACHER)

    response = await client.post(
        "/api/auth/login", json={"email": TEACHER["email"], "password": TEACHER["password"]}
    )

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "teacher"


async def test_same_telegram_user_gets_one_account(client, monkeypatch) -> None:
    """Повторный вход из мессенджера не плодит вторую учётную запись."""
    from app.config import get_settings

    token = "12345:test-bot-token"
    monkeypatch.setattr(get_settings(), "telegram_bot_token", token)
    init_data = telegram_init_data(777, token)

    first = await client.post(
        "/api/auth/miniapp", json={"init_data": init_data, "platform": "telegram"}
    )
    second = await client.post(
        "/api/auth/miniapp", json={"init_data": init_data, "platform": "telegram"}
    )

    assert first.status_code == second.status_code == 200
    assert first.json()["user"]["id"] == second.json()["user"]["id"]
    assert first.json()["user"]["role"] == "student"
    # у ученика из мессенджера почты нет — значит и войти по паролю он не может
    assert first.json()["user"]["email"] is None


async def test_forged_init_data_is_rejected(client, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "telegram_bot_token", "12345:test-bot-token")
    forged = telegram_init_data(778, "другой-токен")

    response = await client.post(
        "/api/auth/miniapp", json={"init_data": forged, "platform": "telegram"}
    )

    assert response.status_code == 401


async def test_public_config_exposes_only_bot_username(client, monkeypatch) -> None:
    """Экрану входа нужно имя бота — и ничего кроме него."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "telegram_bot_username", "kompas_test_bot")

    response = await client.get("/api/public-config")

    assert response.status_code == 200
    assert response.json() == {"telegram_bot_username": "kompas_test_bot"}
