"""Проверка, отвечает ли модель на самом деле.

    docker compose exec backend python -m app.check_ai
    python -m app.check_ai                              # локально, из корня проекта

Подбор профессий устроен так, что упасть не может: любая ошибка уводит на
запасной алгоритм. Это правильно для ученика, но делает отладку слепой —
со стороны «модель не настроена» и «модель отвечает» выглядят одинаково.

Здесь ошибки наоборот показываются как есть, вместе с разбором частых причин.
"""

from __future__ import annotations

import asyncio
import sys
import textwrap

from app.config import get_settings

ПРОФИЛЬ = {
    "investigative": 4.8,
    "realistic": 4.2,
    "conventional": 3.0,
    "social": 2.5,
    "artistic": 2.0,
    "enterprising": 1.8,
}

# Совет по классу исключения — когда ответа от сервера не было вовсе.
ПО_КЛАССУ = {
    "ConnectTimeout": (
        "Соединение не установилось. Адрес выдачи токена ngw.devices.sberbank.ru "
        "доступен не отовсюду — проверьте его с этой машины: "
        "curl -m 10 https://ngw.devices.sberbank.ru:9443/"
    ),
    "ConnectError": (
        "Не удалось соединиться. Если выше упомянут сертификат — это НУЦ Минцифры: "
        "либо укажите GIGACHAT_CA_BUNDLE, либо для пробы GIGACHAT_VERIFY_SSL=false."
    ),
    "ReadTimeout": (
        "Соединение есть, но ответа не дождались — модель думает дольше таймаута."
    ),
}

# Совет по тексту ответа сервера. Проверяется раньше класса: ответ конкретнее.
ПО_ТЕКСТУ = (
    ("no such model", (
        "Такой модели нет у вашей учётной записи. Имя «GigaChat» без версии Сбер "
        "больше не обслуживает. Доступны GigaChat-2, GigaChat-2-Pro, GigaChat-2-Max, "
        "GigaChat-3-Ultra — точное имя впишите в GIGACHAT_MODEL."
    )),
    ("certificate", (
        "Сертификат НУЦ Минцифры: Сбер подписан им, а в стандартном наборе доверенных "
        "его нет. Либо добавьте сертификат и укажите GIGACHAT_CA_BUNDLE, либо для "
        "быстрой пробы GIGACHAT_VERIFY_SSL=false — боевому стенду это не годится."
    )),
    ("401", "Ключ не принят. Нужен Authorization key из личного кабинета, не client secret."),
    ("unauthorized", "Ключ не принят: проверьте GIGACHAT_CREDENTIALS."),
    ("403", (
        "Доступ запрещён — часто это несовпадение GIGACHAT_SCOPE с типом учётной "
        "записи: GIGACHAT_API_PERS для физлиц, _B2B и _CORP для компаний."
    )),
    ("scope", "Не тот GIGACHAT_SCOPE для вашей учётной записи."),
    ("name or service not known", "DNS не разрешает адрес API — сеть этой машины."),
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


def подсказка(exc: Exception) -> str | None:
    """Совет по исключению.

    Текст ошибки обрезается до заголовков ответа. В них попадаются слова вроде
    `keep-alive: timeout=15`, и поиск по всей строке однажды выдал диагноз
    «сеть не отвечает» там, где сеть работала, а не совпало имя модели.
    """
    текст = str(exc).split("Headers(")[0].lower()
    for кусок, совет in ПО_ТЕКСТУ:
        if кусок in текст:
            return совет
    return ПО_КЛАССУ.get(exc.__class__.__name__)


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
        совет = подсказка(exc)
        if совет:
            print()
            print(textwrap.fill(совет, width=76, initial_indent="   ", subsequent_indent="   "))
        return 1

    print()
    print(f"ОТВЕТ: {', '.join(предметы)}")
    print()
    print("Модель отвечает, строгая схема работает — подбор пойдёт через неё,")
    print("а не через запасной алгоритм.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
