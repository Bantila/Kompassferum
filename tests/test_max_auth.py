"""Вход в мини-приложение из MAX.

MAX подписывает initData так же, как Telegram: секрет — HMAC-SHA256 от токена
бота с ключом «WebAppData», им подписывается отсортированная строка параметров
без hash (dev.max.ru/docs/webapps/validation). Проверяем, что подпись сходится,
что чужим токеном её не подделать и что аккаунт заводится на платформе max.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from app.config import get_settings
from app.services.miniapp_auth import verify_max, verify_telegram

MAX_TOKEN = "max-bot-token"
TG_TOKEN = "12345:telegram-bot-token"


def init_data(
    token: str,
    *,
    user_id: int = 424242,
    auth_date: int | None = None,
    extra: dict | None = None,
) -> str:
    """Подписанная строка запуска — ровно как её собирает мессенджер."""
    fields = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "user": json.dumps(
            {"id": user_id, "first_name": "Артём", "last_name": "К.", "username": "artem"},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        **(extra or {}),
    }
    check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@pytest.fixture
def tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "max_bot_token", MAX_TOKEN)
    monkeypatch.setattr(settings, "telegram_bot_token", TG_TOKEN)


def test_valid_max_init_data_is_accepted(tokens) -> None:
    profile = verify_max(init_data(MAX_TOKEN))

    assert profile is not None
    assert profile["platform"] == "max"
    assert profile["external_id"] == "424242"
    assert profile["first_name"] == "Артём"


def test_signature_from_another_bot_is_rejected(tokens) -> None:
    """Подпись чужим токеном не должна открывать вход."""
    assert verify_max(init_data("чужой-токен")) is None


def test_max_and_telegram_signatures_are_not_interchangeable(tokens) -> None:
    """Строка от Telegram не должна проходить как MAX, и наоборот."""
    assert verify_max(init_data(TG_TOKEN)) is None
    assert verify_telegram(init_data(MAX_TOKEN)) is None


def test_tampered_field_breaks_signature(tokens) -> None:
    """Подменить id пользователя, сохранив прежнюю подпись, нельзя."""
    подписано = init_data(MAX_TOKEN, user_id=111)
    подделка = подписано.replace("%22id%22%3A111", "%22id%22%3A222")

    assert подделка != подписано, "подмена не удалась — тест бы ничего не проверял"
    assert verify_max(подделка) is None


def test_duplicate_parameter_is_rejected(tokens) -> None:
    """Дубль параметра позволил бы подобрать подпись под лишнюю копию поля."""
    valid = init_data(MAX_TOKEN)
    hash_value = dict(pair.split("=", 1) for pair in valid.split("&"))["hash"]

    assert verify_max(f"{valid}&hash={hash_value}") is None


def test_stale_init_data_is_rejected(tokens) -> None:
    """Данные живут сутки: открытую неделю назад вкладку не пускаем."""
    вчерашний = int(time.time()) - 25 * 60 * 60

    assert verify_max(init_data(MAX_TOKEN, auth_date=вчерашний)) is None


def test_without_token_nothing_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без MAX_BOT_TOKEN проверять нечем — вход закрыт, а не открыт всем."""
    monkeypatch.setattr(get_settings(), "max_bot_token", "")

    assert verify_max(init_data(MAX_TOKEN)) is None


def test_garbage_is_rejected(tokens) -> None:
    for мусор in ("", "не-строка-запроса", "hash=abc", "user=не-json&hash=abc"):
        assert verify_max(мусор) is None


async def test_login_through_max_creates_student(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """Сквозной вход: подпись MAX заводит ученика без пароля и без почты."""
    monkeypatch.setattr(get_settings(), "max_bot_token", MAX_TOKEN)

    response = await client.post(
        "/api/auth/miniapp", json={"init_data": init_data(MAX_TOKEN), "platform": "max"}
    )

    assert response.status_code == 200
    профиль = response.json()["user"]
    assert профиль["role"] == "student"
    assert профиль["email"] is None
    assert профиль["max_user_id"] == "max_424242"
