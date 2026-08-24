"""Вебхуки мессенджеров и привязка бота к аккаунту.

Вебхук всегда отвечает 200: если вернуть ошибку, платформа начнёт повторять
доставку одного и того же события, и ученик получит несколько одинаковых
сообщений. Все сбои уходят в лог.
"""

from __future__ import annotations

import hmac
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session
from app.models import BotAccount, User
from app.routers.auth import get_current_user
from app.schemas.bot import LinkBotRequest, LinkBotResponse
from app.services import bot_transport
from app.services.bot_core import BotReply, handle

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bot", tags=["bot"])

OK = {"status": "ok"}


async def _process(session: AsyncSession, event, sender) -> dict[str, Any]:
    """Событие → ответ → отправка.

    Любая ошибка гасится здесь: вебхук обязан ответить 200, иначе мессенджер
    сочтёт доставку неудачной и будет слать то же событие снова, а ученик
    получит поток одинаковых сообщений.
    """
    settings = get_settings()
    try:
        reply = await handle(session, event, app_url=settings.app_public_url or None)
        await session.commit()
    except Exception:  # noqa: BLE001 — причину пишем в лог, наружу отдаём извинение
        logger.exception("Сбой обработки события бота (%s)", event.platform)
        await session.rollback()
        reply = BotReply(text="Что-то пошло не так на моей стороне. Попробуй ещё раз чуть позже.")

    await sender(event.chat_id, reply)
    return OK


@router.post("/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    settings = get_settings()
    if settings.telegram_webhook_secret:
        if not x_telegram_bot_api_secret_token or not hmac.compare_digest(
            x_telegram_bot_api_secret_token, settings.telegram_webhook_secret
        ):
            logger.warning("Вебхук Telegram: неверный секрет, запрос отклонён")
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный секрет")

    try:
        update = await request.json()
    except ValueError:
        return OK

    event = bot_transport.parse_telegram(update)
    if event is None or not event.external_id:
        return OK
    return await _process(session, event, bot_transport.send_telegram)


@router.post("/max")
async def max_webhook(
    request: Request,
    x_max_bot_api_secret: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Вебхук MAX. Логика та же, отличается только разбор и отправка.

    Секрет задаётся при подписке (POST /subscriptions) и приходит обратно как
    есть в заголовке X-Max-Bot-Api-Secret — платформа не подписывает тело, а
    просто возвращает значение, поэтому сверяем строки.
    """
    settings = get_settings()
    if settings.max_webhook_secret:
        if not x_max_bot_api_secret or not hmac.compare_digest(
            x_max_bot_api_secret, settings.max_webhook_secret
        ):
            logger.warning("Вебхук MAX: неверная подпись, запрос отклонён")
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверная подпись запроса")

    try:
        update = await request.json()
    except ValueError:
        return OK

    event = bot_transport.parse_max(update)
    if event is None or not event.external_id:
        logger.info("Вебхук MAX: событие не распознано: %s", str(update)[:300])
        return OK
    return await _process(session, event, bot_transport.send_max)


@router.post("/link", response_model=LinkBotResponse)
async def link_bot(
    payload: LinkBotRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> LinkBotResponse:
    """Привязать бота к аккаунту по коду, который бот прислал в чат.

    Код вводится в приложении, где пользователь уже вошёл, — поэтому владелец
    аккаунта известен достоверно и подменить его нельзя.
    """
    code = payload.code.strip().upper()
    account = await session.scalar(select(BotAccount).where(BotAccount.link_code == code))
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Код не найден — попроси бота прислать новый")

    account.user_id = user.id
    account.link_code = None
    await session.commit()
    logger.info("Бот %s привязан к пользователю %s", account.platform, user.max_user_id)
    return LinkBotResponse(platform=account.platform, linked=True)


@router.get("/status", response_model=LinkBotResponse)
async def link_status(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
) -> LinkBotResponse:
    account = await session.scalar(select(BotAccount).where(BotAccount.user_id == user.id))
    if account is None:
        return LinkBotResponse(platform="", linked=False)
    return LinkBotResponse(platform=account.platform, linked=True)
