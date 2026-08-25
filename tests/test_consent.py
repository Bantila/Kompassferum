"""Согласие на обработку персональных данных.

152-ФЗ требует не галочку, а подтверждаемый факт: кто, когда и на какую
редакцию документа согласился — и возможность согласие отозвать, после чего
обработка прекращается. Проверяем, что без согласия результат не сохраняется,
что отзыв действительно удаляет данные, а не помечает их, и что после отзыва
тест не принимается снова.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from sqlalchemy import func, select

from app.config import get_settings
from app.database import SessionLocal
from app.models import Consent, Recommendation, TestResult, User
from app.services import consent as service

TOKEN = "12345:test-bot-token"


def init_data(user_id: int) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "user": json.dumps(
            {"id": user_id, "first_name": f"Ученик{user_id}"},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


async def войти(client, monkeypatch, user_id: int = 900) -> dict:
    monkeypatch.setattr(get_settings(), "telegram_bot_token", TOKEN)
    ответ = await client.post(
        "/api/auth/miniapp", json={"init_data": init_data(user_id), "platform": "telegram"}
    )
    assert ответ.status_code == 200
    токен = ответ.json()["access_token"]
    return {"Authorization": f"Bearer {токен}"}


async def _сдать(client, max_user_id: str, answers: dict):
    return await client.post(
        "/api/tests/submit", json={"max_user_id": max_user_id, "answers": answers}
    )


async def _результатов(max_user_id: str) -> int:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.max_user_id == max_user_id))
        if user is None:
            return 0
        return await session.scalar(
            select(func.count()).select_from(TestResult).where(TestResult.user_id == user.id)
        )


async def test_submit_without_consent_is_refused(client, full_answers) -> None:
    """Прохождение — данные ребёнка: без записанного согласия не сохраняем."""
    ответ = await _сдать(client, "no_consent", full_answers)

    assert ответ.status_code == 403
    assert await _результатов("no_consent") == 0, "отказ не должен оставлять данные"


async def test_consent_opens_the_test(client, monkeypatch, full_answers) -> None:
    заголовки = await войти(client, monkeypatch, user_id=901)

    выдача = await client.post("/api/consent", json={}, headers=заголовки)
    сдача = await _сдать(client, "telegram_901", full_answers)

    assert выдача.status_code == 201
    assert сдача.status_code == 201


async def test_status_reports_absence_and_presence(client, monkeypatch) -> None:
    заголовки = await войти(client, monkeypatch, user_id=902)

    до = await client.get("/api/consent", headers=заголовки)
    await client.post("/api/consent", json={"granted_by": "parent"}, headers=заголовки)
    после = await client.get("/api/consent", headers=заголовки)

    assert до.json()["granted"] is False
    assert после.json()["granted"] is True
    assert после.json()["granted_by"] == "parent", "кто дал согласие — часть реестра"
    assert после.json()["document_version"] == service.CURRENT_VERSION


async def test_revocation_erases_data_not_just_flags_it(client, monkeypatch, full_answers) -> None:
    """Сохранённые прохождения при отозванном согласии — это по-прежнему хранение.

    Поэтому отзыв обязан удалять, а не помечать: пометка оставила бы данные
    ребёнка в базе, то есть обработку продолжающейся.
    """
    заголовки = await войти(client, monkeypatch, user_id=903)
    await client.post("/api/consent", json={}, headers=заголовки)
    assert (await _сдать(client, "telegram_903", full_answers)).status_code == 201
    assert await _результатов("telegram_903") == 1

    отзыв = await client.delete("/api/consent", headers=заголовки)

    assert отзыв.status_code == 200
    assert отзыв.json()["deleted_records"] >= 1
    assert await _результатов("telegram_903") == 0, "результаты обязаны исчезнуть"


async def test_revocation_removes_recommendations_too(client, monkeypatch, full_answers) -> None:
    """Рекомендации выведены из ответов ребёнка — они тоже его данные."""
    заголовки = await войти(client, monkeypatch, user_id=904)
    await client.post("/api/consent", json={}, headers=заголовки)
    await _сдать(client, "telegram_904", full_answers)

    await client.delete("/api/consent", headers=заголовки)

    async with SessionLocal() as session:
        осталось = await session.scalar(select(func.count()).select_from(Recommendation))
    assert осталось == 0


async def test_test_is_closed_after_revocation(client, monkeypatch, full_answers) -> None:
    """Отзыв — не разовая уборка: обработка прекращается и дальше."""
    заголовки = await войти(client, monkeypatch, user_id=905)
    await client.post("/api/consent", json={}, headers=заголовки)
    await client.delete("/api/consent", headers=заголовки)

    повтор = await _сдать(client, "telegram_905", full_answers)

    assert повтор.status_code == 403


async def test_consent_can_be_given_again(client, monkeypatch, full_answers) -> None:
    """Отзыв не должен быть приговором — человек вправе согласиться снова."""
    заголовки = await войти(client, monkeypatch, user_id=906)
    await client.post("/api/consent", json={}, headers=заголовки)
    await client.delete("/api/consent", headers=заголовки)

    снова = await client.post("/api/consent", json={}, headers=заголовки)

    assert снова.status_code == 201
    assert (await _сдать(client, "telegram_906", full_answers)).status_code == 201


async def test_revocation_is_recorded_even_without_prior_consent(client, monkeypatch) -> None:
    """Иначе следующая сдача запишет данные как ни в чём не бывало."""
    заголовки = await войти(client, monkeypatch, user_id=907)

    await client.delete("/api/consent", headers=заголовки)

    async with SessionLocal() as session:
        строка = await session.scalar(select(Consent))
    assert строка is not None and строка.revoked_at is not None


async def test_outdated_version_is_visible(client, monkeypatch) -> None:
    """Текст согласия меняется — приложение должно узнать, что пора переспросить."""
    заголовки = await войти(client, monkeypatch, user_id=908)
    await client.post("/api/consent", json={}, headers=заголовки)

    async with SessionLocal() as session:
        строка = await session.scalar(select(Consent))
        строка.document_version = "2020-01-01"
        await session.commit()

    состояние = await client.get("/api/consent", headers=заголовки)

    assert состояние.json()["outdated"] is True


async def test_consent_requires_login(client) -> None:
    """Согласие привязано к человеку — анонимно его не дать и не отозвать."""
    assert (await client.get("/api/consent")).status_code == 401
    assert (await client.post("/api/consent", json={})).status_code == 401
    assert (await client.delete("/api/consent")).status_code == 401


async def test_unknown_granter_is_rejected(client, monkeypatch) -> None:
    """В реестре должно стоять осмысленное значение, а не что прислали."""
    заголовки = await войти(client, monkeypatch, user_id=909)

    ответ = await client.post("/api/consent", json={"granted_by": "кот"}, headers=заголовки)

    assert ответ.status_code == 422
