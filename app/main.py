"""Точка входа FastAPI для «Компаса»."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.config import Settings, get_settings
from app.database import engine
from app.routers import auth, classes, practice, recommendations, teacher, tests, webhook

logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("«Компас» запускается, модель: %s", settings.openrouter_model)
    if settings.jwt_secret == Settings.model_fields["jwt_secret"].default:
        logger.warning(
            "JWT_SECRET не задан — используется дефолтный. Для стенда обязательно "
            "задайте свой в .env, иначе токены подделываются тривиально."
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
app.include_router(tests.router)
app.include_router(practice.router)
app.include_router(recommendations.router)
app.include_router(teacher.router)
app.include_router(classes.router)
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
