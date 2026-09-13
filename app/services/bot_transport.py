"""Адаптеры мессенджеров: разбор входящего события и отправка ответа.

Здесь и только здесь знают про конкретную платформу. Ядро (bot_core) работает
с BotEvent/BotReply и о существовании Telegram или MAX не подозревает.

MAX — целевая платформа. Telegram остаётся отладочным адаптером и включается,
только если задан TELEGRAM_BOT_TOKEN.
"""

from __future__ import annotations

import logging
import ssl
from typing import Any

import certifi
import httpx

from app.config import RUSSIAN_TRUSTED_CA_BUNDLE, get_settings
from app.services.bot_core import BotEvent, BotReply

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT_SECONDS = 15.0

_max_ssl_context: ssl.SSLContext | bool | None = None


def max_ssl_context() -> ssl.SSLContext | bool:
    """SSL-контекст для запросов к MAX: обычный набор доверенных корней
    (certifi) плюс НУЦ Минцифры, а не замена набора на один этот корень —
    иначе тем же контекстом нельзя было бы сходить больше никуда."""
    global _max_ssl_context
    if _max_ssl_context is None:
        settings = get_settings()
        if not settings.max_verify_ssl:
            _max_ssl_context = False
        else:
            context = ssl.create_default_context(cafile=certifi.where())
            bundle = settings.max_ca_bundle or str(RUSSIAN_TRUSTED_CA_BUNDLE)
            context.load_verify_locations(cafile=bundle)
            _max_ssl_context = context
    return _max_ssl_context


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
#
# Сверено с dev.max.ru/docs-api и моделями официальной библиотеки
# max-messenger/max-botapi-python — не только с описанием, но и с
# pydantic-схемами событий, поэтому формы ниже, в отличие от прежней
# версии, не обобщение по аналогии с Telegram, а собранные по частям
# реальные структуры трёх разных апдейтов.

# у bot_started нет вложенного "message" — событие плоское:
# {"update_type": "bot_started", "chat_id": ..., "user": {"user_id": ...}}
# у message_created/message_edited есть message.sender/recipient/body.text
# у message_callback есть callback.user/callback_id/payload и message.recipient


def parse_max(update: dict[str, Any]) -> BotEvent | None:
    """Событие MAX → общее событие."""
    update_type = update.get("update_type")

    if update_type == "bot_started":
        user = update.get("user") or {}
        return BotEvent(
            platform="max",
            external_id=str(user.get("user_id", "")),
            chat_id=str(update.get("chat_id", "")),
            text="/start",
            first_name=user.get("first_name", ""),
        )

    if update_type == "message_callback":
        callback = update.get("callback") or {}
        user = callback.get("user") or {}
        message = update.get("message") or {}
        recipient = message.get("recipient") or {}
        return BotEvent(
            platform="max",
            external_id=str(user.get("user_id", "")),
            chat_id=_max_recipient_id(recipient),
            payload=callback.get("payload"),
            first_name=user.get("first_name", ""),
            callback_id=callback.get("callback_id"),
        )

    if update_type in ("message_created", "message_edited"):
        message = update.get("message") or {}
        sender = message.get("sender") or {}
        recipient = message.get("recipient") or {}
        body = message.get("body") or {}
        return BotEvent(
            platform="max",
            external_id=str(sender.get("user_id", "")),
            chat_id=_max_recipient_id(recipient),
            text=body.get("text", ""),
            first_name=sender.get("first_name", ""),
        )

    return None


# префикс личного диалога: recipient.chat_id у MAX бывает не заполнен, тогда
# адресовать нужно через user_id — а BotEvent.chat_id один на оба случая
_MAX_DIALOG_PREFIX = "dialog:"


def _max_recipient_id(recipient: dict[str, Any]) -> str:
    chat_id = recipient.get("chat_id")
    if chat_id is not None:
        return str(chat_id)
    return f"{_MAX_DIALOG_PREFIX}{recipient.get('user_id', '')}"


async def send_max(chat_id: str, reply: BotReply) -> bool:
    settings = get_settings()
    if not settings.max_bot_token:
        logger.warning("MAX_BOT_TOKEN не задан — ответ не отправлен")
        return False

    attachments: list[dict[str, Any]] = []
    rows: list[list[dict[str, Any]]] = []
    if reply.app_url:
        # open_app, а не link: только так мини-приложение получает initData и
        # входит само — обычная ссылка открыла бы внешний браузер без подписи.
        rows.append(
            [{"type": "open_app", "text": "Открыть Компас", "web_app": settings.max_bot_username}]
            if settings.max_bot_username
            else [{"type": "link", "text": "Открыть Компас", "url": reply.app_url}]
        )
    for row in reply.buttons:
        # callback — единственный тип, который приходит боту обратно как
        # message_callback с тем же payload; parse_max уже умеет его читать
        rows.append([{"type": "callback", "text": label, "payload": label} for label in row])
    if rows:
        attachments.append({"type": "inline_keyboard", "payload": {"buttons": rows}})

    body: dict[str, Any] = {"text": reply.text, "format": "html"}
    if attachments:
        body["attachments"] = attachments

    # personal-диалог без chat_id закодирован префиксом в parse_max —
    # тогда адресуем сообщение через ?user_id=, а не ?chat_id=
    if chat_id.startswith(_MAX_DIALOG_PREFIX):
        query = f"user_id={chat_id[len(_MAX_DIALOG_PREFIX):]}"
    else:
        query = f"chat_id={chat_id}"

    return await _post(
        f"{settings.max_api_base}/messages?{query}",
        body,
        headers={"Authorization": settings.max_bot_token},
        verify=max_ssl_context(),
    )


async def answer_max_callback(callback_id: str, notification: str | None = None) -> bool:
    """Подтвердить нажатие inline-кнопки.

    Без этого у нажавшего кнопку крутится индикатор загрузки до таймаута —
    платформа не знает, что бот вообще получил callback.
    """
    settings = get_settings()
    if not settings.max_bot_token:
        return False
    body: dict[str, Any] = {}
    if notification:
        body["notification"] = notification
    return await _post(
        f"{settings.max_api_base}/answers?callback_id={callback_id}",
        body,
        headers={"Authorization": settings.max_bot_token},
        verify=max_ssl_context(),
    )


async def get_max_bot_info() -> dict[str, Any] | None:
    """GET /me — имя и id бота, нужны для диплинка и кнопки open_app."""
    settings = get_settings()
    if not settings.max_bot_token:
        return None
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, verify=max_ssl_context()) as client:
            response = await client.get(
                f"{settings.max_api_base}/me",
                headers={"Authorization": settings.max_bot_token},
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        logger.error("Не удалось получить данные бота MAX: %s", exc)
        return None


# ──────────────────────────── общее ─────────────────────────────

async def _post(
    url: str,
    body: dict[str, Any],
    headers: dict[str, str] | None = None,
    verify: ssl.SSLContext | bool = True,
) -> bool:
    """Отправка с проглатыванием ошибок: сбой мессенджера не должен ронять вебхук —
    иначе платформа сочтёт доставку неуспешной и начнёт слать событие заново."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, verify=verify) as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            return True
    except httpx.HTTPStatusError as exc:
        logger.error("Мессенджер вернул %s: %s", exc.response.status_code, exc.response.text[:300])
    except httpx.HTTPError as exc:
        logger.error("Не удалось отправить сообщение: %s", exc)
    return False
