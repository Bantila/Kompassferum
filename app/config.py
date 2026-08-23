"""Настройки приложения. Всё читается из переменных окружения / .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://kompas:kompas@postgres:5432/kompas"

    # OpenRouter
    openrouter_api_key: str = ""
    openrouter_model: str = "moonshotai/kimi-k2"
    openrouter_url: str = "https://openrouter.ai/api/v1/chat/completions"
    openrouter_timeout_seconds: float = 30.0

    # Вебхук MAX
    max_webhook_secret: str = ""
    max_bot_token: str = ""

    # Telegram — площадка для отладки бота, пока нет доступа к платформе MAX
    telegram_bot_token: str = ""
    # секрет вебхука: Telegram шлёт его в заголовке X-Telegram-Bot-Api-Secret-Token
    telegram_webhook_secret: str = ""

    # адрес мини-приложения — бот присылает на него кнопку
    app_public_url: str = ""

    # Аутентификация. Секрет обязан задаваться через окружение: на дефолте
    # приложение поднимется (чтобы не ломать локальный запуск), но залогирует
    # предупреждение — с таким секретом чужой токен подделывается тривиально.
    jwt_secret: str = "dev-only-insecure-secret"
    jwt_algorithm: str = "HS256"
    jwt_ttl_hours: int = 24 * 30  # месяц: школьник не должен логиниться каждый день

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
