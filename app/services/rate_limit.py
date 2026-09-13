"""Ограничение частоты запросов.

Без него один скрипт забивает базу прохождениями, а вход педагога подбирается
перебором: пароль проверяется bcrypt-ом, но ничто не мешает пробовать вечно.

Счётчик держится в памяти процесса. Для одного контейнера этого достаточно, и
это осознанный размен: внешнее хранилище (redis) ради счётчика на прототипе —
лишняя движущаяся часть, которая сама может упасть и утащить с собой вход.

ponytail: счётчик в памяти процесса; при нескольких репликах backend лимит
станет общим только через внешнее хранилище, например redis.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

# ключ (имя правила + клиент) → времена последних попаданий
_попадания: dict[str, deque[float]] = defaultdict(deque)

# Ключей столько же, сколько уникальных адресов. Чтобы память не росла
# бесконечно на длинной аптайме, изредка выбрасываем полностью протухшие.
_ПОРОГ_УБОРКИ = 10_000


def _клиент(request: Request) -> str:
    """Кто стучится.

    Берём X-Real-IP: Caddy перезаписывает его адресом соединения
    (`header_up X-Real-IP {remote_host}`). Backend не публикует порт в Compose,
    поэтому внешний клиент не может обойти прокси и подставить свой адрес.
    При прямом запуске backend это правило доверия нужно обеспечить отдельно.
    """
    реальный = request.headers.get("x-real-ip")
    if реальный:
        return реальный.strip()
    return request.client.host if request.client else "unknown"


def _убрать_протухшее(сейчас: float) -> None:
    for ключ in [k for k, v in _попадания.items() if not v or сейчас - v[-1] > 3600]:
        _попадания.pop(ключ, None)


def reset() -> None:
    """Обнулить счётчики. Нужно тестам, чтобы они не влияли друг на друга."""
    _попадания.clear()


def limit(name: str, times: int, seconds: int):
    """Зависимость FastAPI: не больше `times` запросов за `seconds` с адреса.

    Окно скользящее, а не фиксированное: на границе фиксированных окон можно
    без помех отправить двойную порцию запросов.
    """

    async def проверка(request: Request) -> None:
        сейчас = time.monotonic()
        ключ = f"{name}:{_клиент(request)}"
        окно = _попадания[ключ]

        while окно and сейчас - окно[0] > seconds:
            окно.popleft()

        if len(окно) >= times:
            ждать = int(seconds - (сейчас - окно[0])) + 1
            logger.warning("Лимит %s исчерпан для %s", name, ключ.split(":", 1)[1])
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Слишком много запросов, попробуйте позже",
                headers={"Retry-After": str(ждать)},
            )

        окно.append(сейчас)
        if len(_попадания) > _ПОРОГ_УБОРКИ:
            _убрать_протухшее(сейчас)

    return проверка
