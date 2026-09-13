"""Кто чьи данные может прочитать.

Два разных вопроса, которые легко перепутать. Первый: свои ли это данные —
история прохождений и рекомендации отдаются только тому, о ком они. Второй:
свой ли это класс — педагог работает лишь со своими классами.

Оба места защищены в коде, но защита из тех, что молча исчезает при
рефакторинге: убрал зависимость из сигнатуры — и эндпоинт открыт. Поэтому
тесты здесь, а не в файлах отдельных роутеров.
"""

from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.models import SchoolClass, User, UserRole
from app.services import consent
from app.services.security import create_access_token, hash_password


async def _заголовок(max_user_id: str) -> dict:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.max_user_id == max_user_id))
        return {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def _ученик(client, max_user_id: str, full_answers: dict) -> dict:
    # без записанного согласия /submit отвечает 403 — это данные ребёнка
    async with SessionLocal() as session:
        user = User(max_user_id=max_user_id, role=UserRole.student, full_name="Ученик")
        session.add(user)
        await session.flush()
        await consent.grant(session, user.id)
        await session.commit()

    ответ = await client.post(
        "/api/tests/submit", json={"max_user_id": max_user_id, "answers": full_answers}
    )
    assert ответ.status_code == 201
    return {"result_id": ответ.json()["test_result_id"], **await _заголовок(max_user_id)}


async def _педагог(почта: str) -> tuple[dict, str]:
    """Педагог с собственным классом. Возвращает заголовок и id класса."""
    async with SessionLocal() as session:
        teacher = User(
            max_user_id=f"web_{почта}",
            email=почта,
            hashed_password=hash_password("very-secret"),
            full_name=почта,
            role=UserRole.teacher,
            is_active=True,
        )
        session.add(teacher)
        await session.flush()
        класс = SchoolClass(
            name="7Б", teacher_id=teacher.id, join_code=почта[:6].upper().ljust(6, "X")
        )
        session.add(класс)
        await session.commit()
        return {"Authorization": f"Bearer {create_access_token(teacher.id)}"}, str(класс.id)


# --- свои ли это данные ------------------------------------------------------


async def test_history_requires_login(client, full_answers) -> None:
    await _ученик(client, "telegram_111", full_answers)

    ответ = await client.get("/api/users/telegram_111/history")

    assert ответ.status_code == 401


async def test_history_of_someone_else_is_not_readable(client, full_answers) -> None:
    """max_user_id — это id в мессенджере, его подбирают перебором.

    Без проверки история любого ребёнка читалась бы по одному угаданному числу.
    """
    await _ученик(client, "telegram_222", full_answers)
    чужие = await _ученик(client, "telegram_333", full_answers)

    ответ = await client.get("/api/users/telegram_222/history", headers=чужие)

    assert ответ.status_code == 404, "чужая история не должна открываться"


async def test_own_history_is_readable(client, full_answers) -> None:
    свои = await _ученик(client, "telegram_444", full_answers)

    ответ = await client.get("/api/users/telegram_444/history", headers=свои)

    assert ответ.status_code == 200
    assert ответ.json()["attempts"] == 1


async def test_missing_user_and_foreign_user_answer_alike(client, full_answers) -> None:
    """Разные ответы позволяли бы перебором выяснять, кто пользуется сервисом."""
    свои = await _ученик(client, "telegram_555", full_answers)
    await _ученик(client, "telegram_666", full_answers)

    несуществующий = await client.get("/api/users/telegram_999999/history", headers=свои)
    чужой = await client.get("/api/users/telegram_666/history", headers=свои)

    assert несуществующий.status_code == чужой.status_code == 404


async def test_recommendations_require_login(client, full_answers) -> None:
    ученик = await _ученик(client, "telegram_777", full_answers)

    ответ = await client.get(f"/api/recommendations/{ученик['result_id']}")

    assert ответ.status_code == 401


async def test_foreign_recommendations_are_not_readable(client, full_answers) -> None:
    """Подбор профессий выведен из ответов ребёнка — это его данные."""
    чужой_результат = (await _ученик(client, "telegram_888", full_answers))["result_id"]
    свои = await _ученик(client, "telegram_999", full_answers)

    ответ = await client.get(f"/api/recommendations/{чужой_результат}", headers=свои)

    assert ответ.status_code == 404


async def test_teacher_cannot_read_individual_results(client, full_answers) -> None:
    """Педагогу полагается обезличенная сводка, а не разбор конкретного ребёнка."""
    ученик = await _ученик(client, "telegram_1010", full_answers)
    учитель, _ = await _педагог("first@school.ru")

    рекомендации = await client.get(
        f"/api/recommendations/{ученик['result_id']}", headers=учитель
    )
    история = await client.get("/api/users/telegram_1010/history", headers=учитель)

    assert рекомендации.status_code == 404
    assert история.status_code == 404


# --- свой ли это класс -------------------------------------------------------


async def test_teacher_sees_only_own_class_summary(client) -> None:
    свой_учитель, свой_класс = await _педагог("own@school.ru")
    чужой_учитель, чужой_класс = await _педагог("other@school.ru")

    ответ = await client.get(
        f"/api/teacher/class-summary?class_id={чужой_класс}", headers=свой_учитель
    )

    assert ответ.status_code == 404, "чужой класс не должен находиться"


async def test_teacher_cannot_open_foreign_leaderboard(client) -> None:
    """В рейтинге видны имена учеников — чужой класс тем более закрыт."""
    свой_учитель, _ = await _педагог("lead1@school.ru")
    _, чужой_класс = await _педагог("lead2@school.ru")

    ответ = await client.get(
        f"/api/teacher/classes/{чужой_класс}/leaderboard", headers=свой_учитель
    )

    assert ответ.status_code == 404


async def test_teacher_cannot_list_foreign_assignments(client) -> None:
    свой_учитель, _ = await _педагог("asg1@school.ru")
    _, чужой_класс = await _педагог("asg2@school.ru")

    ответ = await client.get(
        f"/api/teacher/classes/{чужой_класс}/assignments", headers=свой_учитель
    )

    assert ответ.status_code == 404


async def test_teacher_cannot_assign_work_to_foreign_class(client) -> None:
    """Иначе чужому классу можно назначить что угодно от своего имени."""
    свой_учитель, _ = await _педагог("asg3@school.ru")
    _, чужой_класс = await _педагог("asg4@school.ru")

    ответ = await client.post(
        f"/api/teacher/classes/{чужой_класс}/assignments",
        json={"subject": "mathematics", "title": "Дроби"},
        headers=свой_учитель,
    )

    assert ответ.status_code == 404


async def test_student_cannot_reach_teacher_endpoints(client, full_answers) -> None:
    ученик = await _ученик(client, "telegram_1212", full_answers)
    _, класс = await _педагог("stud@school.ru")

    ответ = await client.get(f"/api/teacher/class-summary?class_id={класс}", headers=ученик)

    assert ответ.status_code == 403
