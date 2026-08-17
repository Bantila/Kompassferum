"""Точка входа FastAPI для «Компаса»."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.database import engine
from app.routers import recommendations, teacher, tests, webhook

logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("«Компас» запускается, модель: %s", get_settings().openrouter_model)
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

app.include_router(tests.router)
app.include_router(recommendations.router)
app.include_router(teacher.router)
app.include_router(webhook.router)


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
