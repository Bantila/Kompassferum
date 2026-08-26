"""Проверка, отвечает ли модель на самом деле.

    docker compose exec backend python -m app.check_ai

Подбор профессий устроен так, что упасть не может: любая ошибка уводит на
запасной алгоритм. Это правильно для ученика, но делает отладку слепой —
со стороны «модель не настроена» и «модель отвечает» выглядят одинаково.

Здесь ошибки наоборот показываются как есть, вместе с разбором частых причин.
"""

from __future__ import annotations

import asyncio
import sys

from app.config import get_settings

ПРОФИЛЬ = {
    "investigative": 4.8,
    "realistic": 4.2,
    "conventional": 3.0,
    "social": 2.5,
    "artistic": 2.0,
    "enterprising": 1.8,
}

# Подсказки по обрывкам текста ошибки: что именно чинить.
ПРИЧИНЫ = (
    ("certificate", "Сертификат НУЦ Минцифры. Сбер подписан им, а в наборе доверенных\n"
                    "   его нет. Либо добавить сертификат в образ и указать GIGACHAT_CA_BUNDLE,\n"
                    "   либо для быстрой пробы GIGACHAT_VERIFY_SSL=false (боевому стенду не годится)."),
    ("ssl", "Ошибка TLS — почти наверняка тот же сертификат Минцифры."),
    ("401", "Ключ не принят. Проверьте GIGACHAT_CREDENTIALS — нужен Authorization key\n"
            "   из личного кабинета, а не client secret."),
    ("unauthorized", "Ключ не принят: проверьте GIGACHAT_CREDENTIALS."),
    ("403", "Доступ запрещён. Часто это несовпадение GIGACHAT_SCOPE с типом учётной\n"
            "   записи: GIGACHAT_API_PERS для физлиц, _B2B и _CORP для компаний."),
    ("scope", "Не тот GIGACHAT_SCOPE для вашей учётной записи."),
    ("timeout", "Модель не ответила вовремя — сеть до Сбера с этого сервера."),
    ("timed out", "Модель не ответила вовремя — сеть до Сбера с этого сервера."),
    ("name or service not known", "DNS не разрешает адрес API — сеть сервера."),
)


def настройки() -> str:
    s = get_settings()
    return "\n".join((
        f"  провайдер:        {s.ai_provider}",
        f"  модель:           {s.gigachat_model}",
        f"  scope:            {s.gigachat_scope}",
        f"  ключ задан:       {'да' if s.gigachat_credentials else 'НЕТ'}",
        f"  проверка TLS:     {'включена' if s.gigachat_verify_ssl else 'ОТКЛЮЧЕНА'}",
        f"  свой сертификат:  {s.gigachat_ca_bundle or 'не указан'}",
    ))


def подсказка(текст: str) -> str | None:
    низ = текст.lower()
    for кусок, совет in ПРИЧИНЫ:
        if кусок in низ:
            return совет
    return None


async def main() -> int:
    print()
    print("Настройки:")
    print(настройки())
    print()

    s = get_settings()
    if s.ai_provider.strip().lower() != "gigachat":
        print(f"AI_PROVIDER={s.ai_provider}, не gigachat — проверять нечего.")
        return 1
    if not s.gigachat_credentials:
        print("GIGACHAT_CREDENTIALS пуст — подбор всегда пойдёт запасным алгоритмом.")
        return 1

    print(f"Спрашиваю {s.gigachat_model}: какие предметы проверить у этого ученика…")
    from app.services.test_planner import _ask_gigachat

    try:
        предметы = await _ask_gigachat(ПРОФИЛЬ)
    except Exception as exc:  # noqa: BLE001 — здесь ошибка и есть результат
        print()
        print(f"ОШИБКА: {exc.__class__.__name__}: {exc}")
        совет = подсказка(f"{exc.__class__.__name__} {exc}")
        if совет:
            print()
            print(f"   {совет}")
        return 1

    print()
    print(f"ОТВЕТ: {', '.join(предметы)}")
    print()
    print("Модель отвечает, строгая схема работает — подбор пойдёт через неё,")
    print("а не через запасной алгоритм.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
