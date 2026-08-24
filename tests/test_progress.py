"""Черновик теста на сервере.

Раньше ответы жили только в localStorage: очистка данных браузера, другой
телефон или вход из бота — и тест начинался с нуля. Теперь черновик привязан
к аккаунту. Проверяем, что он переживает «смену устройства», что чужой
черновик недоступен и что после сдачи теста он исчезает.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from app.config import get_settings

TOKEN = "12345:test-bot-token"


def init_data(user_id: int) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": user_id, "first_name": f"Ученик{user_id}"},
                           ensure_ascii=False, separators=(",", ":")),
    }
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


async def войти(client, monkeypatch: pytest.MonkeyPatch, user_id: int = 501) -> dict:
    """Заголовок с токеном ученика — вход через подпись мессенджера."""
    monkeypatch.setattr(get_settings(), "telegram_bot_token", TOKEN)
    response = await client.post(
        "/api/auth/miniapp", json={"init_data": init_data(user_id), "platform": "telegram"}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


ОТВЕТЫ = {"a1": 4, "a2": 2, "b1_k1": {"selected_index": 1, "time_spent_seconds": 12.0}}


async def test_progress_is_empty_for_new_user(client, monkeypatch) -> None:
    заголовки = await войти(client, monkeypatch)

    response = await client.get("/api/tests/progress", headers=заголовки)

    assert response.status_code == 200
    assert response.json()["answers"] == {}
    assert response.json()["answered"] == 0


async def test_progress_survives_new_device(client, monkeypatch) -> None:
    """Главное свойство: ответы находятся с другого устройства, где кеша нет."""
    заголовки = await войти(client, monkeypatch)
    await client.put("/api/tests/progress", json={"answers": ОТВЕТЫ}, headers=заголовки)

    # «второй телефон» — тот же аккаунт, новый вход, пустой localStorage
    другие_заголовки = await войти(client, monkeypatch)
    response = await client.get("/api/tests/progress", headers=другие_заголовки)

    assert response.json()["answers"] == ОТВЕТЫ
    assert response.json()["answered"] == 3
    assert response.json()["updated_at"] is not None


async def test_saving_replaces_answers(client, monkeypatch) -> None:
    """Ответы приходят целиком: иначе нельзя вернуться назад и переответить."""
    заголовки = await войти(client, monkeypatch)
    await client.put("/api/tests/progress", json={"answers": ОТВЕТЫ}, headers=заголовки)

    await client.put("/api/tests/progress", json={"answers": {"a1": 5}}, headers=заголовки)
    итог = (await client.get("/api/tests/progress", headers=заголовки)).json()

    assert итог["answers"] == {"a1": 5}


async def test_plan_is_kept_between_devices(client, monkeypatch) -> None:
    """План блока B тоже в черновике: иначе на другом устройстве будут другие предметы."""
    заголовки = await войти(client, monkeypatch)
    план = {"subjects": [{"subject": "physics", "title": "Физика"}]}

    await client.put("/api/tests/progress", json={"answers": ОТВЕТЫ, "plan": план},
                     headers=заголовки)
    итог = (await client.get("/api/tests/progress", headers=заголовки)).json()

    assert итог["plan"] == план


async def test_progress_is_not_shared_between_students(client, monkeypatch) -> None:
    первый = await войти(client, monkeypatch, user_id=601)
    await client.put("/api/tests/progress", json={"answers": ОТВЕТЫ}, headers=первый)

    второй = await войти(client, monkeypatch, user_id=602)
    чужой = (await client.get("/api/tests/progress", headers=второй)).json()

    assert чужой["answers"] == {}


async def test_progress_requires_login(client) -> None:
    assert (await client.get("/api/tests/progress")).status_code == 401
    assert (await client.put("/api/tests/progress", json={"answers": {}})).status_code == 401


async def test_reset_clears_progress(client, monkeypatch) -> None:
    заголовки = await войти(client, monkeypatch)
    await client.put("/api/tests/progress", json={"answers": ОТВЕТЫ}, headers=заголовки)

    удаление = await client.delete("/api/tests/progress", headers=заголовки)

    assert удаление.status_code == 204
    assert (await client.get("/api/tests/progress", headers=заголовки)).json()["answers"] == {}


async def test_submit_clears_progress(client, monkeypatch) -> None:
    """После сдачи теста приложение не должно предлагать «продолжить»."""
    заголовки = await войти(client, monkeypatch, user_id=701)
    await client.put("/api/tests/progress", json={"answers": ОТВЕТЫ}, headers=заголовки)

    submit = await client.post(
        "/api/tests/submit",
        json={"max_user_id": "telegram_701", "answers": ОТВЕТЫ},
        headers=заголовки,
    )

    assert submit.status_code == 201
    assert (await client.get("/api/tests/progress", headers=заголовки)).json()["answered"] == 0
