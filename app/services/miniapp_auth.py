"""Проверка подписи мини-приложения.

Мессенджер открывает наш сайт во встроенном браузере и передаёт строку initData
с данными пользователя, подписанную секретом бота. Проверив подпись, сервер
достоверно знает, кто открыл приложение, — и вход не требует ни пароля, ни кода.

Telegram: секрет = HMAC(«WebAppData», токен бота), подпись лежит в поле hash.
MAX устроен так же (window.WebApp.initData), но точная схема подписи станет
известна с доступом к платформе — под неё оставлено место в verify_max.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any
from urllib.parse import parse_qsl

from app.config import get_settings

logger = logging.getLogger(__name__)

# сутки: столько живёт открытая вкладка мини-приложения, дальше просим открыть заново
MAX_AUTH_AGE_SECONDS = 24 * 60 * 60


def verify_telegram(init_data: str) -> dict[str, Any] | None:
    """initData → данные пользователя, либо None если подпись не сходится."""
    settings = get_settings()
    if not settings.telegram_bot_token or not init_data:
        return None

    try:
        fields = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        logger.warning("initData: строка не разбирается")
        return None

    received_hash = fields.pop("hash", "")
    if not received_hash:
        return None

    # подписывается всё, кроме самого hash, отсортированное по имени поля
    check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret_key = hmac.new(b"WebAppData", settings.telegram_bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        logger.warning("initData: подпись не совпала")
        return None

    auth_date = fields.get("auth_date")
    if auth_date and auth_date.isdigit():
        age = time.time() - int(auth_date)
        if age > MAX_AUTH_AGE_SECONDS:
            logger.info("initData: данные устарели (%.0f ч)", age / 3600)
            return None

    try:
        user = json.loads(fields.get("user", "{}"))
    except ValueError:
        return None
    if not user.get("id"):
        return None

    return {
        "platform": "telegram",
        "external_id": str(user["id"]),
        "first_name": user.get("first_name", ""),
        "last_name": user.get("last_name", ""),
        "username": user.get("username", ""),
    }


def verify_max(init_data: str) -> dict[str, Any] | None:
    """Заглушка для MAX: включится, когда появится доступ к платформе."""
    logger.info("Проверка initData MAX пока не реализована — нет доступа к платформе")
    return None


def full_name_from(profile: dict[str, Any]) -> str:
    parts = [profile.get("first_name", ""), profile.get("last_name", "")]
    name = " ".join(p for p in parts if p).strip()
    return name or profile.get("username", "") or "Ученик"
