"""Приём событий от платформы MAX.

ЗАГЛУШКА. Проверка секрета, логирование и 200 OK реализованы по-настоящему,
разбор payload — нет.

TODO: точный формат входящего payload и способ подписи запроса уточняются
после получения документации MAX от организаторов хакатона. Ожидаем что-то
вида {"update_type": "message_created", "message": {"sender": {"user_id": ...},
"body": {"text": "..."}}}, но подтверждения пока нет. Когда формат придёт:
  1) описать Pydantic-схему события вместо сырого dict;
  2) роутить update_type → сценарий бота (старт теста, следующий вопрос, показ
     рекомендаций), состояние сессии брать из TestResult.raw_answers;
  3) уточнить имя заголовка с подписью (сейчас X-Max-Signature) и, если MAX
     подписывает тело HMAC-ом, сверять hmac.new(secret, body).hexdigest(),
     а не сам секрет.
"""

from __future__ import annotations

import hmac
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhook", tags=["webhook"])


@router.post("/max")
async def max_webhook(
    request: Request,
    x_max_signature: str | None = Header(default=None),
) -> dict[str, Any]:
    settings = get_settings()

    if not settings.max_webhook_secret:
        logger.error("MAX_WEBHOOK_SECRET не задан — вебхук отключён")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Вебхук не настроен на сервере"
        )

    # compare_digest вместо == — чтобы время сравнения не зависело от того,
    # сколько первых символов секрета угадано
    if not x_max_signature or not hmac.compare_digest(
        x_max_signature, settings.max_webhook_secret
    ):
        logger.warning("Вебхук MAX: неверная подпись, запрос отклонён")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверная подпись запроса")

    try:
        payload = await request.json()
    except ValueError:
        logger.warning("Вебхук MAX: тело запроса — не JSON")
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Ожидается JSON в теле запроса"
        ) from None

    logger.info("Вебхук MAX: получено событие %s", payload)
    return {"status": "ok", "received": True}
