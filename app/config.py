"""Настройки приложения. Всё читается из переменных окружения / .env."""

import secrets
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://kompas:kompas@postgres:5432/kompas"

    # Какой провайдер отвечает за подбор профессий:
    # gigachat | openrouter | none (всегда rule-based)
    ai_provider: str = "none"

    # GigaChat — российская модель, основной вариант для защиты проекта.
    # credentials — Authorization key из личного кабинета, обменивается
    # на токен доступа; SDK делает это сам и обновляет токен по истечении.
    gigachat_credentials: str = ""
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_model: str = "GigaChat"
    gigachat_base_url: str = "https://api.giga.chat/v1"
    # Сбер отдаёт TLS-цепочку, подписанную НУЦ Минцифры: в стандартном
    # наборе сертификатов её нет. Пока корневой сертификат не установлен
    # на машине или сервере, запрос падает на проверке TLS — тогда
    # проверку приходится отключать этой настройкой. Для боевого стенда
    # правильнее поставить сертификат, а не выключать проверку.
    gigachat_verify_ssl: bool = True
    # Путь к корневому сертификату НУЦ Минцифры, если он установлен на сервере.
    # Задан — проверка TLS работает штатно и отключать её не нужно.
    gigachat_ca_bundle: str = ""

    # OpenRouter
    openrouter_api_key: str = ""
    openrouter_model: str = "moonshotai/kimi-k2"
    openrouter_url: str = "https://openrouter.ai/api/v1/chat/completions"
    openrouter_timeout_seconds: float = 30.0

    # MAX — целевая платформа
    max_webhook_secret: str = ""
    max_bot_token: str = ""
    # https://platform-api2.max.ru по документации; botapi.max.ru — рабочий legacy-алиас
    max_api_base: str = "https://platform-api2.max.ru"
    # имя бота без @ — нужно для диплинка (max.ru/<username>) и кнопки open_app
    max_bot_username: str = ""
    # MAX подписан НУЦ Минцифры (Russian Trusted Root/Sub CA) — сертификата
    # нет в стандартном наборе (certifi), поэтому без него любой запрос
    # к MAX падает на проверке TLS. В отличие от GigaChat, для MAX это не
    # опция: обхода через rule-based нет, платформа просто недоступна.
    # Поэтому сертификат вшит в репозиторий (app/certs/) и подключается
    # сам — эта настройка только для переопределения путём или для сервера
    # с уже установленным доверием, где нужен другой путь.
    max_ca_bundle: str = ""
    # false отключает проверку TLS для MAX целиком: только для отладки,
    # для боевого стенда — нет
    max_verify_ssl: bool = True

    # Telegram — необязательный отладочный адаптер, включается только если задан токен.
    # Основная платформа — MAX; ядро сценариев (bot_core) от выбора не зависит.
    telegram_bot_token: str = ""
    # имя бота без @ — нужно приложению, чтобы дать ссылку на вход
    telegram_bot_username: str = ""
    # секрет вебхука: Telegram шлёт его в заголовке X-Telegram-Bot-Api-Secret-Token
    telegram_webhook_secret: str = ""

    # адрес мини-приложения — бот присылает на него кнопку
    app_public_url: str = ""

    @field_validator("max_bot_username", "telegram_bot_username")
    @classmethod
    def _strip_at(cls, value: str) -> str:
        """Имя бота нужно без @ — в диплинке и в поле web_app кнопки open_app
        символ @ ломает ссылку. Оператор часто копирует имя прямо из
        мессенджера вместе с @, поэтому срезаем сами, а не полагаемся на то,
        что .env заполнят правильно."""
        return value.lstrip("@")

    # Аутентификация. Секрет обязан задаваться через окружение. Если его нет,
    # приложение поднимется (чтобы не ломать локальный запуск), но подставит
    # случайный секрет: известное всем дефолтное значение позволило бы кому
    # угодно подписать себе токен педагога. Плата — при рестарте все токены
    # протухают, и это заметно, в отличие от тихой дыры.
    jwt_secret: str = "dev-only-insecure-secret"
    jwt_algorithm: str = "HS256"
    jwt_ttl_hours: int = 24 * 30  # месяц: школьник не должен логиниться каждый день

    log_level: str = "INFO"


DEFAULT_JWT_SECRET = "dev-only-insecure-secret"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.jwt_secret == DEFAULT_JWT_SECRET:
        # 32 байта: короче — предупреждение PyJWT о слабом ключе для HS256
        settings.jwt_secret = secrets.token_urlsafe(32)
    return settings
