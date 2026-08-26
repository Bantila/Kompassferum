"""Точка входа FastAPI для «Компаса»."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.config import get_settings
from app.database import engine
from app.routers import auth, bot, consent, classes, practice, recommendations, teacher, tests

logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # Печатаем модель того провайдера, который выбран. Раньше здесь всегда стоял
    # openrouter_model — а у него есть значение по умолчанию, поэтому лог
    # показывал «moonshotai/kimi-k2» даже при включённом GigaChat и заставлял
    # думать, что настройки не применились.
    провайдер = settings.ai_provider.strip().lower()
    модель = {
        "gigachat": settings.gigachat_model,
        "openrouter": settings.openrouter_model,
    }.get(провайдер, "запасной алгоритм без модели")
    logger.info("«Компас» запускается, подбор профессий: %s (%s)", провайдер, модель)
    if not os.getenv("JWT_SECRET"):
        logger.warning(
            "JWT_SECRET не задан — подставлен случайный на время работы процесса. "
            "Подделать токен нельзя, но при каждом рестарте все входы слетают. "
            "Задайте постоянный JWT_SECRET в .env."
        )
    yield
    await engine.dispose()
    logger.info("«Компас» остановлен")


app = FastAPI(
    title="Компас — ИИ-навигатор по профессиям",
    description=(
        "Backend прототипа для MAX/Сферум: психометрический тест из 74 вопросов, "
        "подбор 5 профессий через OpenRouter и агрегированная сводка для педагога."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# Мини-приложение MAX открывается в вебвью со своего origin.
# TODO: сузить до конкретного домена MAX, когда он будет известен.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

class NoCacheStaticFiles(StaticFiles):
    """Статика мини-приложения меняется часто — браузер не должен кэшировать её
    надолго, иначе версии HTML/JS/CSS расходятся (стучится в старый app.js
    вместе с новым index.html) и фронтенд ломается без явной ошибки."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", NoCacheStaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """Мини-приложение для ученика. Кабинет педагога — /static/teacher.html."""
    return FileResponse(STATIC_DIR / "index.html")


app.include_router(auth.router)
app.include_router(consent.router)
app.include_router(tests.router)
app.include_router(practice.router)
app.include_router(recommendations.router)
app.include_router(teacher.router)
app.include_router(classes.router)
app.include_router(bot.router)


@app.get("/api/public-config", tags=["service"])
async def public_config() -> dict[str, str]:
    """Настройки, нужные приложению до входа. Секретов здесь нет."""
    return {"telegram_bot_username": get_settings().telegram_bot_username}


@app.get("/health", tags=["service"])
async def health() -> JSONResponse:
    """Проверка живости вместе с доступностью БД — для docker healthcheck."""
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — health-check не должен падать стеком
        logger.error("Health-check: БД недоступна: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "database": "unavailable"},
        )
    return JSONResponse(content={"status": "ok", "database": "ok"})
