"""Подтверждение роли педагога кодом приглашения.

Роль teacher открывает сводку по классу — пусть обезличенную, но это данные о
детях. Раньше эту роль назначал себе сам заявитель: хватало почты и пароля.
Теперь её подтверждает тот, кто уже работает в школе.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import TeacherInvite, User, UserRole
from app.services import invites

ПЕДАГОГ = {
    "email": "novy@school.ru",
    "password": "very-secret",
    "full_name": "Пётр Иванович",
}


async def _зарегистрировать(client, код: str, email: str = ПЕДАГОГ["email"]):
    return await client.post(
        "/api/auth/register", json={**ПЕДАГОГ, "email": email, "invite_code": код}
    )


async def _счёт_пользователей() -> int:
    async with SessionLocal() as session:
        return await session.scalar(select(func.count()).select_from(User))


async def test_valid_code_lets_a_teacher_in(client, invite_code) -> None:
    ответ = await _зарегистрировать(client, invite_code)

    assert ответ.status_code == 201
    assert ответ.json()["user"]["role"] == "teacher"


async def test_registration_without_code_is_rejected(client) -> None:
    """Код обязателен на уровне схемы — забыть его нельзя."""
    ответ = await client.post("/api/auth/register", json=ПЕДАГОГ)

    assert ответ.status_code == 422


async def test_made_up_code_does_not_open_the_door(client) -> None:
    ответ = await _зарегистрировать(client, "AAAA-BBBB-CCCC")

    assert ответ.status_code == 403


async def test_code_works_only_once(client, invite_code) -> None:
    """Многоразовый код расходится по переписке и перестаёт что-либо подтверждать."""
    assert (await _зарегистрировать(client, invite_code)).status_code == 201

    второй = await _зарегистрировать(client, invite_code, email="drugoy@school.ru")

    assert второй.status_code == 403


async def test_expired_code_is_refused(client) -> None:
    """Просроченный код не должен работать: приглашение — не бессрочный пропуск."""
    async with SessionLocal() as session:
        протухший = TeacherInvite(
            code="OLDX-OLDX-OLDX",
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        session.add(протухший)
        await session.commit()

    assert (await _зарегистрировать(client, "OLDX-OLDX-OLDX")).status_code == 403


async def test_failed_code_leaves_no_account_behind(client) -> None:
    """Аккаунт создаётся до проверки кода — откат обязан его убрать.

    Иначе почта окажется занятой недорегистрированной записью, и человек с
    правильным кодом получит 409 вместо входа.
    """
    было = await _счёт_пользователей()

    assert (await _зарегистрировать(client, "NOPE-NOPE-NOPE")).status_code == 403

    assert await _счёт_пользователей() == было, "неудачная попытка оставила аккаунт"


async def test_code_is_forgiving_about_case_and_spaces(client, invite_code) -> None:
    """Код диктуют голосом и переписывают с бумажки."""
    ответ = await _зарегистрировать(client, f"  {invite_code.lower()}  ")

    assert ответ.status_code == 201


async def test_generated_codes_avoid_lookalike_characters() -> None:
    """0/O и 1/I в коде превращаются в «код не подходит» на ровном месте."""
    коды = "".join(invites.generate_code() for _ in range(200)).replace("-", "")

    assert not set(коды) & set("O0I1L")


async def test_teacher_can_invite_a_colleague(client, invite_code) -> None:
    """Цепочка доверия: подтверждённый педагог приглашает следующего."""
    первый = await _зарегистрировать(client, invite_code)
    токен = первый.json()["access_token"]

    выдача = await client.post(
        "/api/auth/invites",
        json={"note": "Сидорова, 8А"},
        headers={"Authorization": f"Bearer {токен}"},
    )

    assert выдача.status_code == 201
    новый_код = выдача.json()["code"]
    коллега = await _зарегистрировать(client, новый_код, email="sidorova@school.ru")
    assert коллега.status_code == 201


async def test_stranger_cannot_issue_invites(client) -> None:
    """Без входа код не выписывается — иначе приглашение печатал бы кто угодно."""
    ответ = await client.post("/api/auth/invites", json={"note": "кто-то"})

    assert ответ.status_code == 401


async def test_student_cannot_issue_invites(client, full_answers) -> None:
    """Ученик не должен уметь производить педагогов."""
    async with SessionLocal() as session:
        ученик = User(max_user_id="tg_555", role=UserRole.student, full_name="Ученик")
        session.add(ученик)
        await session.commit()
        айди = ученик.id

    from app.services.security import create_access_token

    ответ = await client.post(
        "/api/auth/invites",
        json={"note": "себе"},
        headers={"Authorization": f"Bearer {create_access_token(айди)}"},
    )

    assert ответ.status_code == 403


async def test_redeem_is_atomic(client, invite_code) -> None:
    """Один код — один педагог, даже если гасить его дважды подряд.

    Проверка «прочитать, убедиться, записать» пропустила бы обоих: между
    чтением и записью успевает вклиниться второй запрос.
    """
    async with SessionLocal() as session:
        первый = await invites.redeem(session, invite_code, None)
        второй = await invites.redeem(session, invite_code, None)
        await session.commit()

    assert [первый, второй] == [True, False]
