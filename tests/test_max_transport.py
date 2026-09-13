"""Адаптер MAX: разбор событий и сборка исходящих запросов.

Формы апдейтов ниже — не обобщение по аналогии с Telegram, а структуры,
собранные по dev.max.ru и pydantic-моделям max-messenger/max-botapi-python
(bot_started плоский, message_created/message_callback — вложенные).
Раньше bot_started разбирался неверно (как message_created) — первое
нажатие «Начать» не давало боту вообще ничего, см. test_parse_bot_started.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.services import bot_transport
from app.services.bot_core import BotReply


@pytest.fixture
def max_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "max_bot_token", "max-bot-token")


# ─────────────────────────── разбор событий ───────────────────────────


def test_parse_bot_started() -> None:
    """Реальная форма bot_started — плоская, без вложенного message."""
    update = {
        "update_type": "bot_started",
        "timestamp": 1,
        "chat_id": 555,
        "user": {"user_id": 111, "first_name": "Артём"},
    }

    event = bot_transport.parse_max(update)

    assert event is not None
    assert event.external_id == "111"
    assert event.chat_id == "555"
    assert event.text == "/start"
    assert event.first_name == "Артём"


def test_parse_message_created() -> None:
    update = {
        "update_type": "message_created",
        "timestamp": 1,
        "message": {
            "sender": {"user_id": 111, "first_name": "Артём"},
            "recipient": {"chat_id": 555},
            "timestamp": 1,
            "body": {"mid": "m1", "seq": 1, "text": "Дай задачу"},
        },
    }

    event = bot_transport.parse_max(update)

    assert event is not None
    assert event.external_id == "111"
    assert event.chat_id == "555"
    assert event.text == "Дай задачу"


def test_parse_message_created_in_personal_dialog_without_chat_id() -> None:
    """В личном диалоге recipient может не содержать chat_id, только user_id —
    тогда send_max должен будет адресовать ответ через ?user_id=."""
    update = {
        "update_type": "message_created",
        "timestamp": 1,
        "message": {
            "sender": {"user_id": 111, "first_name": "Артём"},
            "recipient": {"user_id": 111},
            "timestamp": 1,
            "body": {"mid": "m1", "seq": 1, "text": "привет"},
        },
    }

    event = bot_transport.parse_max(update)

    assert event is not None
    assert event.chat_id == "dialog:111"


def test_parse_message_callback() -> None:
    update = {
        "update_type": "message_callback",
        "timestamp": 1,
        "callback": {
            "timestamp": 1,
            "callback_id": "cb-1",
            "payload": "Мой прогресс",
            "user": {"user_id": 111, "first_name": "Артём"},
        },
        "message": {
            "sender": {"user_id": 999, "first_name": "Компас"},
            "recipient": {"chat_id": 555},
            "timestamp": 1,
            "body": {"mid": "m1", "seq": 1, "text": "Выбери, что сделать"},
        },
    }

    event = bot_transport.parse_max(update)

    assert event is not None
    assert event.external_id == "111"
    assert event.chat_id == "555"
    assert event.payload == "Мой прогресс"
    assert event.callback_id == "cb-1"


def test_parse_unknown_update_type_is_ignored() -> None:
    assert bot_transport.parse_max({"update_type": "chat_title_changed"}) is None


# ─────────────────────────── сборка ответа ───────────────────────────


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Подменяет сетевой _post и запоминает, с чем его вызвали."""
    calls: dict = {}

    async def fake_post(url, body, headers=None):
        calls["url"] = url
        calls["body"] = body
        calls["headers"] = headers
        return True

    monkeypatch.setattr(bot_transport, "_post", fake_post)
    return calls


async def test_send_max_uses_html_format(max_token, captured) -> None:
    """bot_core верстает ответы HTML-тегами — без format='html' MAX покажет их как текст."""
    await bot_transport.send_max("555", BotReply(text="<b>Верно!</b>"))

    assert captured["body"]["format"] == "html"


async def test_send_max_keyboard_uses_callback_buttons(max_token, captured) -> None:
    """Кнопки должны быть type=callback — это то, что parse_max умеет читать
    обратно в message_callback. Тип message или payload у message-кнопки не
    поддерживается платформой и раньше просто терялся."""
    await bot_transport.send_max("555", BotReply(text="выбери", buttons=[["Дай задачу", "Мой прогресс"]]))

    attachment = captured["body"]["attachments"][0]
    row = attachment["payload"]["buttons"][0]
    assert [b["type"] for b in row] == ["callback", "callback"]
    assert [b["payload"] for b in row] == ["Дай задачу", "Мой прогресс"]


async def test_send_max_app_button_is_open_app_when_username_known(max_token, captured, monkeypatch) -> None:
    """Кнопка мини-приложения должна быть open_app, а не link — иначе оно
    откроется во внешнем браузере без initData, и автовход не сработает."""
    monkeypatch.setattr(get_settings(), "max_bot_username", "kompas_bot")

    await bot_transport.send_max("555", BotReply(text="привет", app_url="https://kompas.example/"))

    button = captured["body"]["attachments"][0]["payload"]["buttons"][0][0]
    assert button["type"] == "open_app"
    assert button["web_app"] == "kompas_bot"


async def test_send_max_app_button_falls_back_to_link_without_username(max_token, captured, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "max_bot_username", "")

    await bot_transport.send_max("555", BotReply(text="привет", app_url="https://kompas.example/"))

    button = captured["body"]["attachments"][0]["payload"]["buttons"][0][0]
    assert button["type"] == "link"
    assert button["url"] == "https://kompas.example/"


async def test_send_max_addresses_chat_by_chat_id(max_token, captured) -> None:
    await bot_transport.send_max("555", BotReply(text="привет"))

    assert "chat_id=555" in captured["url"]


async def test_send_max_addresses_personal_dialog_by_user_id(max_token, captured) -> None:
    """chat_id из parse_max в личном диалоге на деле хранит user_id с префиксом —
    адресовать такое сообщение нужно через ?user_id=, а не ?chat_id=."""
    await bot_transport.send_max("dialog:111", BotReply(text="привет"))

    assert "user_id=111" in captured["url"]
    assert "chat_id=" not in captured["url"]


async def test_send_max_without_token_does_not_call_post(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "max_bot_token", "")
    calls = []
    monkeypatch.setattr(bot_transport, "_post", lambda *a, **kw: calls.append(1))

    result = await bot_transport.send_max("555", BotReply(text="привет"))

    assert result is False
    assert calls == []


# ─────────────────────────── подтверждение callback ───────────────────────────


async def test_answer_max_callback_posts_to_answers_endpoint(max_token, captured) -> None:
    ok = await bot_transport.answer_max_callback("cb-1")

    assert ok is True
    assert "/answers?callback_id=cb-1" in captured["url"]
