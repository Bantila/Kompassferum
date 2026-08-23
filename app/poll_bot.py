"""Запуск бота опросом вместо вебхука — для отладки без публичного адреса.

Вебхуку нужен HTTPS-домен, доступный извне; на машине разработчика его обычно
нет. Опрос (getUpdates) работает откуда угодно и использует те же сценарии,
что и вебхук, поэтому поведение бота ничем не отличается.

    python -m app.poll_bot

На боевом стенде так запускать не нужно — там вебхук.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import get_settings
from app.database import SessionLocal
from app.services import bot_transport
from app.services.bot_core import BotReply, handle

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
logger = logging.getLogger("bot")

LONG_POLL_SECONDS = 25


async def _handle_update(update: dict) -> None:
    event = bot_transport.parse_telegram(update)
    if event is None or not event.external_id:
        return

    settings = get_settings()
    async with SessionLocal() as session:
        try:
            reply = await handle(session, event, app_url=settings.app_public_url or None)
            await session.commit()
        except Exception:  # noqa: BLE001 — один сбойный запрос не должен ронять бота
            logger.exception("Сбой обработки сообщения")
            await session.rollback()
            reply = BotReply(text="Что-то пошло не так на моей стороне. Попробуй ещё раз чуть позже.")

    await bot_transport.send_telegram(event.chat_id, reply)
    logger.info("ответ отправлен в чат %s", event.chat_id)


async def main() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN не задан в .env")

    base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
    async with httpx.AsyncClient(timeout=LONG_POLL_SECONDS + 10) as client:
        # вебхук и опрос несовместимы: пока висит вебхук, getUpdates ничего не отдаёт
        await client.get(f"{base}/deleteWebhook")
        me = (await client.get(f"{base}/getMe")).json()
        logger.info("бот @%s слушает сообщения", me.get("result", {}).get("username", "?"))

        offset = None
        while True:
            try:
                params = {"timeout": LONG_POLL_SECONDS}
                if offset is not None:
                    params["offset"] = offset
                response = await client.get(f"{base}/getUpdates", params=params)
                updates = response.json().get("result", [])
            except httpx.HTTPError as exc:
                logger.warning("сеть недоступна (%s), повтор через 5 с", exc)
                await asyncio.sleep(5)
                continue

            for update in updates:
                offset = update["update_id"] + 1
                await _handle_update(update)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("бот остановлен")
