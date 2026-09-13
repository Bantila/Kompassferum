"""Привязка публичного адреса к боту: вебхук MAX и (опционально) Telegram.

Адрес туннеля меняется при каждом запуске, поэтому настройка вынесена в одну
команду:

    python -m app.setup_bot https://example.trycloudflare.com

Скрипт записывает адрес в .env и подписывает на вебхук те платформы, для
которых задан токен. MAX — целевая платформа; Telegram, если его токен тоже
задан, настраивается тем же вызовом ради удобства локальной отладки.

URL мини-приложения для MAX сюда не входит — в отличие от Telegram, MAX не
даёт сделать это через API: адрес вставляется руками в кабинете
«MAX для партнёров» (Чат-боты → бот → ⋮ → Настройки → поле URL
мини-приложения). Скрипт только напоминает об этом шаге.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import httpx

from app.config import get_settings

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _set_env(key: str, value: str) -> None:
    """Заменить значение в .env или дописать, если ключа там ещё нет."""
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    pattern = re.compile(rf"^{re.escape(key)}=")
    for index, line in enumerate(lines):
        if pattern.match(line):
            lines[index] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _setup_max(client: httpx.AsyncClient, url: str, use_webhook: bool) -> None:
    settings = get_settings()
    webhook_url = f"{url}/api/bot/max"

    if use_webhook:
        response = await client.post(
            f"{settings.max_api_base}/subscriptions",
            json={
                "url": webhook_url,
                "update_types": ["message_created", "message_callback", "bot_started"],
                "secret": settings.max_webhook_secret or None,
            },
            headers={"Authorization": settings.max_bot_token},
        )
        ok = response.status_code < 400
        print("MAX вебхук:", "включён" if ok else response.text[:200])
    else:
        response = await client.request(
            "DELETE",
            f"{settings.max_api_base}/subscriptions",
            params={"url": webhook_url},
            headers={"Authorization": settings.max_bot_token},
        )
        print(
            "MAX вебхук снят — бот работает опросом (python -m app.poll_bot --platform max)"
            if response.status_code < 400
            else f"снять вебхук не удалось: {response.text[:200]}"
        )

    print(
        "\nMAX не даёт прописать URL мини-приложения через API — сделайте это руками:\n"
        "  MAX для партнёров → Чат-боты → ваш бот → ⋮ → Настройки →\n"
        f"  вставьте {url} в поле URL мини-приложения → Сохранить."
    )


async def _setup_telegram(client: httpx.AsyncClient, url: str, use_webhook: bool) -> None:
    settings = get_settings()
    base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"

    menu = await client.post(
        f"{base}/setChatMenuButton",
        json={"menu_button": {"type": "web_app", "text": "Компас", "web_app": {"url": url}}},
    )
    print("Telegram кнопка мини-приложения:", "готова" if menu.json().get("ok") else menu.text[:200])

    if use_webhook:
        hook = await client.post(
            f"{base}/setWebhook",
            json={
                "url": f"{url}/api/bot/telegram",
                "secret_token": settings.telegram_webhook_secret or None,
                "drop_pending_updates": True,
            },
        )
        print("Telegram вебхук:", "включён" if hook.json().get("ok") else hook.text[:200])
    else:
        await client.get(f"{base}/deleteWebhook")
        print("Telegram вебхук снят — бот работает опросом (python -m app.poll_bot --platform telegram)")


async def main() -> int:
    if len(sys.argv) < 2:
        print("Укажите адрес: python -m app.setup_bot https://example.trycloudflare.com")
        return 1

    url = sys.argv[1].rstrip("/")
    if not url.startswith("https://"):
        print("Нужен адрес по HTTPS — мессенджер открывает мини-приложение только по нему.")
        return 1

    use_webhook = "--webhook" in sys.argv
    settings = get_settings()

    if not settings.max_bot_token and not settings.telegram_bot_token:
        print("Ни MAX_BOT_TOKEN, ни TELEGRAM_BOT_TOKEN не заданы в .env")
        return 1

    _set_env("APP_PUBLIC_URL", url)
    print(f"адрес записан в .env: {url}")

    async with httpx.AsyncClient(timeout=20) as client:
        if settings.max_bot_token:
            await _setup_max(client, url, use_webhook)
        else:
            print("MAX_BOT_TOKEN не задан — платформа MAX пропущена")

        if settings.telegram_bot_token:
            await _setup_telegram(client, url, use_webhook)

    print("\nПерезапустите сервер и бота, чтобы новый адрес подхватился.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
