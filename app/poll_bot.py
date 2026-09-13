"""Запуск бота опросом вместо вебхука — для отладки без публичного адреса.

Вебхуку нужен HTTPS-домен, доступный извне; на машине разработчика его обычно
нет. Опрос работает откуда угодно и использует те же сценарии, что и вебхук,
поэтому поведение бота ничем не отличается.

    python -m app.poll_bot                 # платформа определяется по токену
    python -m app.poll_bot --platform max  # явный выбор, если заданы оба токена

На боевом стенде так запускать не нужно — там вебхук. MAX явно предупреждает,
что при активной подписке на вебхук опрос ничего не вернёт, поэтому перед
стартом опроса мы снимаем все подписки бота.
"""

from __future__ import annotations

import asyncio
import logging
import sys

import httpx

from app.config import get_settings
from app.database import SessionLocal
from app.services import bot_transport
from app.services.bot_core import BotReply, handle

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
logger = logging.getLogger("bot")

LONG_POLL_SECONDS = 25


async def _dispatch(event, sender) -> None:
    """Событие → ответ → отправка. Общая часть для Telegram и MAX."""
    settings = get_settings()
    async with SessionLocal() as session:
        try:
            reply = await handle(session, event, app_url=settings.app_public_url or None)
            await session.commit()
        except Exception:  # noqa: BLE001 — один сбойный запрос не должен ронять бота
            logger.exception("Сбой обработки сообщения")
            await session.rollback()
            reply = BotReply(text="Что-то пошло не так на моей стороне. Попробуй ещё раз чуть позже.")

    await sender(event.chat_id, reply)
    logger.info("ответ отправлен в чат %s", event.chat_id)


async def poll_telegram() -> None:
    settings = get_settings()
    base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
    async with httpx.AsyncClient(timeout=LONG_POLL_SECONDS + 10) as client:
        # вебхук и опрос несовместимы: пока висит вебхук, getUpdates ничего не отдаёт
        await client.get(f"{base}/deleteWebhook")
        me = (await client.get(f"{base}/getMe")).json()
        logger.info("Telegram: бот @%s слушает сообщения", me.get("result", {}).get("username", "?"))

        offset = None
        while True:
            try:
                params = {"timeout": LONG_POLL_SECONDS}
                if offset is not None:
                    params["offset"] = offset
                response = await client.get(f"{base}/getUpdates", params=params)
                updates = response.json().get("result", [])
            except httpx.HTTPError as exc:
                logger.warning("Telegram: сеть недоступна (%s), повтор через 5 с", exc)
                await asyncio.sleep(5)
                continue

            for update in updates:
                offset = update["update_id"] + 1
                event = bot_transport.parse_telegram(update)
                if event is None or not event.external_id:
                    continue
                await _dispatch(event, bot_transport.send_telegram)


async def poll_max() -> None:
    settings = get_settings()
    headers = {"Authorization": settings.max_bot_token}
    async with httpx.AsyncClient(timeout=LONG_POLL_SECONDS + 10, verify=bot_transport.max_ssl_context()) as client:
        # вебхук и опрос несовместимы — снимаем все текущие подписки бота
        subscriptions = await client.get(f"{settings.max_api_base}/subscriptions", headers=headers)
        for sub in subscriptions.json().get("subscriptions", []):
            await client.request(
                "DELETE",
                f"{settings.max_api_base}/subscriptions",
                params={"url": sub["url"]},
                headers=headers,
            )

        me = (await client.get(f"{settings.max_api_base}/me", headers=headers)).json()
        logger.info("MAX: бот @%s слушает сообщения", me.get("username", "?"))

        marker = None
        while True:
            try:
                params: dict = {"timeout": LONG_POLL_SECONDS, "limit": 100}
                if marker is not None:
                    params["marker"] = marker
                response = await client.get(
                    f"{settings.max_api_base}/updates", params=params, headers=headers
                )
                payload = response.json()
                updates = payload.get("updates", [])
                marker = payload.get("marker", marker)
            except httpx.HTTPError as exc:
                logger.warning("MAX: сеть недоступна (%s), повтор через 5 с", exc)
                await asyncio.sleep(5)
                continue

            for update in updates:
                event = bot_transport.parse_max(update)
                if event is None or not event.external_id:
                    continue
                await _dispatch(event, bot_transport.send_max)
                if event.callback_id:
                    await bot_transport.answer_max_callback(event.callback_id)


def _pick_platform() -> str:
    settings = get_settings()
    if "--platform" in sys.argv:
        return sys.argv[sys.argv.index("--platform") + 1]
    if settings.max_bot_token and settings.telegram_bot_token:
        raise SystemExit(
            "Заданы оба токена — укажите платформу явно: python -m app.poll_bot --platform max"
        )
    if settings.max_bot_token:
        return "max"
    if settings.telegram_bot_token:
        return "telegram"
    raise SystemExit("Ни MAX_BOT_TOKEN, ни TELEGRAM_BOT_TOKEN не заданы в .env")


async def main() -> None:
    platform = _pick_platform()
    await {"max": poll_max, "telegram": poll_telegram}[platform]()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("бот остановлен")
