"""Привязка публичного адреса к боту: кнопка мини-приложения и вебхук.

Адрес туннеля меняется при каждом запуске, поэтому настройка вынесена в одну
команду:

    python -m app.setup_bot https://example.trycloudflare.com

Скрипт записывает адрес в .env, ставит кнопку мини-приложения слева от поля
ввода и, если попросить, включает вебхук вместо опроса.
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


async def main() -> int:
    if len(sys.argv) < 2:
        print("Укажите адрес: python -m app.setup_bot https://example.trycloudflare.com")
        return 1

    url = sys.argv[1].rstrip("/")
    if not url.startswith("https://"):
        print("Нужен адрес по HTTPS — Telegram открывает мини-приложение только по нему.")
        return 1

    use_webhook = "--webhook" in sys.argv
    settings = get_settings()
    if not settings.telegram_bot_token:
        print("TELEGRAM_BOT_TOKEN не задан в .env")
        return 1

    _set_env("APP_PUBLIC_URL", url)
    print(f"адрес записан в .env: {url}")

    base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
    async with httpx.AsyncClient(timeout=20) as client:
        menu = await client.post(
            f"{base}/setChatMenuButton",
            json={"menu_button": {"type": "web_app", "text": "Компас", "web_app": {"url": url}}},
        )
        print("кнопка мини-приложения:", "готова" if menu.json().get("ok") else menu.text[:200])

        if use_webhook:
            hook = await client.post(
                f"{base}/setWebhook",
                json={
                    "url": f"{url}/api/bot/telegram",
                    "secret_token": settings.telegram_webhook_secret or None,
                    "drop_pending_updates": True,
                },
            )
            print("вебхук:", "включён" if hook.json().get("ok") else hook.text[:200])
        else:
            await client.get(f"{base}/deleteWebhook")
            print("вебхук снят — бот работает опросом (python -m app.poll_bot)")

    print("\nПерезапустите сервер и бота, чтобы новый адрес подхватился.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
