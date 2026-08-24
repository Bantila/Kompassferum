"""Адаптеры мессенджеров: разбор входящего события и отправка ответа.

Здесь и только здесь знают про конкретную платформу. Ядро (bot_core) работает
с BotEvent/BotReply и о существовании Telegram или MAX не подозревает.

Telegram — рабочий адаптер. MAX — каркас: структура запросов взята из
документации dev.max.ru, но без доступа к платформе он не проверен, поэтому
включается только когда задан токен.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings
from app.services.bot_core import BotEvent, BotReply

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
MAX_API = "https://botapi.max.ru"
TIMEOUT_SECONDS = 15.0


# ─────────────────────────── Telegram ───────────────────────────

def parse_telegram(update: dict[str, Any]) -> BotEvent | None:
    """Обновление Telegram → общее событие. None, если событие нам не интересно."""
    message = update.get("message") or update.get("edited_message")
    callback = update.get("callback_query")

    if callback:
        source = callback.get("message") or {}
        user = callback.get("from") or {}
        chat = source.get("chat") or {}
        return BotEvent(
            platform="telegram",
            external_id=str(user.get("id", "")),
            chat_id=str(chat.get("id", user.get("id", ""))),
            payload=callback.get("data"),
            first_name=user.get("first_name", ""),
        )

    if message:
        user = message.get("from") or {}
        chat = message.get("chat") or {}
        return BotEvent(
            platform="telegram",
            external_id=str(user.get("id", "")),
            chat_id=str(chat.get("id", "")),
            text=message.get("text", ""),
            first_name=user.get("first_name", ""),
        )

    return None


async def send_telegram(chat_id: str, reply: BotReply) -> bool:
    settings = get_settings()
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN не задан — ответ не отправлен")
        return False

    body: dict[str, Any] = {
        "chat_id": chat_id,
        "text": reply.text,
        "parse_mode": "HTML",
    }

    if reply.app_url:
        # web_app вместо обычной ссылки: приложение открывается внутри мессенджера
        # и получает подписанные данные пользователя, поэтому вход не нужен.
        # Telegram принимает такую кнопку только с адресом по HTTPS.
        body["reply_markup"] = {
            "inline_keyboard": [[
                {"text": "Открыть Компас", "web_app": {"url": reply.app_url}}
                if reply.app_url.startswith("https://")
                else {"text": "Открыть Компас", "url": reply.app_url}
            ]]
        }
    elif reply.buttons:
        # клавиатура под полем ввода: подписи приходят обычным текстом,
        # ядро разбирает их так же, как набранное вручную
        body["reply_markup"] = {
            "keyboard": [[{"text": label} for label in row] for row in reply.buttons],
            "resize_keyboard": True,
        }

    return await _post(
        TELEGRAM_API.format(token=settings.telegram_bot_token, method="sendMessage"), body
    )


async def set_telegram_menu_button(app_url: str) -> bool:
    """Кнопка слева от поля ввода, открывающая мини-приложение.

    Ставится один раз для всего бота: после этого приложение доступно из чата
    всегда, а не только из сообщения с кнопкой.
    """
    settings = get_settings()
    if not settings.telegram_bot_token or not app_url.startswith("https://"):
        return False
    return await _post(
        TELEGRAM_API.format(token=settings.telegram_bot_token, method="setChatMenuButton"),
        {"menu_button": {"type": "web_app", "text": "Компас", "web_app": {"url": app_url}}},
    )


# ───────────────────────────── MAX ──────────────────────────────

def parse_max(update: dict[str, Any]) -> BotEvent | None:
    """Событие MAX → общее событие.

    Формат по документации: {"update_type": "message_created",
    "message": {"sender": {"user_id": ...}, "recipient": {"chat_id": ...},
    "body": {"text": "..."}}}. Проверить на живой платформе пока негде,
    поэтому разбор написан терпимым к отсутствующим полям.
    """
    update_type = update.get("update_type")

    if update_type == "message_callback":
        callback = update.get("callback") or {}
        user = callback.get("user") or {}
        message = update.get("message") or {}
        recipient = message.get("recipient") or {}
        return BotEvent(
            platform="max",
            external_id=str(user.get("user_id", "")),
            chat_id=str(recipient.get("chat_id", "")),
            payload=callback.get("payload"),
            first_name=user.get("first_name", ""),
        )

    if update_type in ("message_created", "bot_started"):
        message = update.get("message") or {}
        sender = message.get("sender") or {}
        recipient = message.get("recipient") or {}
        body = message.get("body") or {}
        return BotEvent(
            platform="max",
            external_id=str(sender.get("user_id", update.get("user_id", ""))),
            chat_id=str(recipient.get("chat_id", update.get("chat_id", ""))),
            text=body.get("text", "") or ("/start" if update_type == "bot_started" else ""),
            first_name=sender.get("first_name", ""),
        )

    return None


async def send_max(chat_id: str, reply: BotReply) -> bool:
    settings = get_settings()
    if not settings.max_bot_token:
        logger.warning("MAX_BOT_TOKEN не задан — ответ не отправлен")
        return False

    attachments: list[dict[str, Any]] = []
    rows: list[list[dict[str, Any]]] = []
    if reply.app_url:
        rows.append([{"type": "link", "text": "Открыть приложение", "url": reply.app_url}])
    for row in reply.buttons:
        rows.append([{"type": "message", "text": label, "payload": label} for label in row])
    if rows:
        attachments.append({"type": "inline_keyboard", "payload": {"buttons": rows}})

    body: dict[str, Any] = {"text": reply.text}
    if attachments:
        body["attachments"] = attachments

    return await _post(
        f"{MAX_API}/messages?chat_id={chat_id}",
        body,
        headers={"Authorization": settings.max_bot_token},
    )


# ──────────────────────────── общее ─────────────────────────────

async def _post(url: str, body: dict[str, Any], headers: dict[str, str] | None = None) -> bool:
    """Отправка с проглатыванием ошибок: сбой мессенджера не должен ронять вебхук —
    иначе платформа сочтёт доставку неуспешной и начнёт слать событие заново."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            return True
    except httpx.HTTPStatusError as exc:
        logger.error("Мессенджер вернул %s: %s", exc.response.status_code, exc.response.text[:300])
    except httpx.HTTPError as exc:
        logger.error("Не удалось отправить сообщение: %s", exc)
    return False
