"""Классы: педагог создаёт и смотрит свои, ученик вступает по коду.

Все ручки работают от токена: кто ты — берётся из JWT, а не из тела запроса.
Иначе достаточно было подставить чужой id, чтобы управлять чужим классом.
"""

from __future__ import annotations

import logging
import secrets
import string
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import (
    ClassAssignment,
    SchoolClass,
    TaskAttempt,
    TestResult,
    User,
    UserRole,
    UserStats,
)
from app.routers.auth import get_current_user
from app.schemas.school_class import (
    AssignmentOut,
    ClassOut,
    CreateAssignmentRequest,
    CreateClassRequest,
    JoinClassRequest,
    JoinClassResponse,
    LeaderboardResponse,
    LeaderboardRow,
)
from app.services.gamification import level_of
from app.services.integrity import summary_line as integrity_note

logger = logging.getLogger(__name__)

router = APIRouter(tags=["classes"])

# без похожих друг на друга символов (0/O, 1/I/L) — код часто диктуют вслух в классе
JOIN_CODE_ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "01OIL")
JOIN_CODE_LENGTH = 6


def _require_teacher(user: User) -> User:
    if user.role != UserRole.teacher:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Доступно только педагогу")
    return user


async def _students_count(session: AsyncSession, class_id) -> int:
    return await session.scalar(select(func.count(User.id)).where(User.class_id == class_id)) or 0


def _class_out(school_class: SchoolClass, students_count: int) -> ClassOut:
    return ClassOut(
        id=school_class.id,
        name=school_class.name,
        join_code=school_class.join_code,
        students_count=students_count,
        created_at=school_class.created_at,
    )


async def _generate_unique_join_code(session: AsyncSession) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(JOIN_CODE_ALPHABET) for _ in range(JOIN_CODE_LENGTH))
        if await session.scalar(select(SchoolClass).where(SchoolClass.join_code == code)) is None:
            return code
    raise RuntimeError("Не удалось сгенерировать уникальный код класса")


@router.post("/api/teacher/classes", response_model=ClassOut)
async def create_class(
    payload: CreateClassRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ClassOut:
    """Создать класс и получить код для учеников.

    Идемпотентно по имени: повторное создание класса с тем же названием
    возвращает существующий, а не плодит дубликаты (двойной клик по кнопке).
    """
    teacher = _require_teacher(user)
    name = payload.name.strip()

    existing = await session.scalar(
        select(SchoolClass).where(
            SchoolClass.teacher_id == teacher.id, func.lower(SchoolClass.name) == name.lower()
        )
    )
    if existing is not None:
        return _class_out(existing, await _students_count(session, existing.id))

    school_class = SchoolClass(
        name=name, teacher_id=teacher.id, join_code=await _generate_unique_join_code(session)
    )
    session.add(school_class)
    await session.commit()
    await session.refresh(school_class)
    return _class_out(school_class, 0)


@router.get("/api/teacher/classes", response_model=list[ClassOut])
async def list_classes(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
) -> list[ClassOut]:
    """Классы этого педагога с количеством присоединившихся учеников."""
    teacher = _require_teacher(user)
    rows = (
        await session.execute(
            select(SchoolClass, func.count(User.id))
            .outerjoin(User, User.class_id == SchoolClass.id)
            .where(SchoolClass.teacher_id == teacher.id)
            .group_by(SchoolClass.id)
            .order_by(SchoolClass.created_at.desc())
        )
    ).all()
    return [_class_out(school_class, count) for school_class, count in rows]


async def _owned_class(session: AsyncSession, teacher: User, class_id) -> SchoolClass:
    school_class = await session.scalar(
        select(SchoolClass).where(SchoolClass.id == class_id, SchoolClass.teacher_id == teacher.id)
    )
    if school_class is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Класс не найден среди ваших классов")
    return school_class


@router.get("/api/teacher/classes/{class_id}/leaderboard", response_model=LeaderboardResponse)
async def leaderboard(
    class_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> LeaderboardResponse:
    """Рейтинг класса по опыту.

    В отличие от обезличенной сводки здесь видны имена: это рабочий список
    своего класса, педагог и так знает, кто у него учится. Доступ — только
    владельцу класса.
    """
    teacher = _require_teacher(user)
    school_class = await _owned_class(session, teacher, class_id)

    rows = (
        await session.execute(
            select(
                User.id,
                User.full_name,
                func.coalesce(UserStats.xp, 0),
                func.coalesce(UserStats.streak_days, 0),
                func.count(TaskAttempt.id),
                func.count(TaskAttempt.id).filter(TaskAttempt.is_correct.is_(True)),
                func.count(func.distinct(TestResult.id)),
            )
            .outerjoin(UserStats, UserStats.user_id == User.id)
            .outerjoin(TaskAttempt, TaskAttempt.user_id == User.id)
            .outerjoin(TestResult, TestResult.user_id == User.id)
            .where(User.class_id == class_id, User.role == UserRole.student)
            .group_by(User.id, User.full_name, UserStats.xp, UserStats.streak_days)
            .order_by(func.coalesce(UserStats.xp, 0).desc(), User.full_name)
        )
    ).all()

    # Пометка о доверии берётся из последнего прохождения: если ученик
    # прокликал тест, педагог должен видеть это рядом с его цифрами, иначе
    # решения принимаются по числам, за которыми ничего нет.
    заметки: dict[uuid.UUID, str] = {}
    прохождения = (
        await session.execute(
            select(TestResult.user_id, TestResult.integrity)
            .where(TestResult.user_id.in_([row[0] for row in rows]))
            .order_by(TestResult.user_id, TestResult.completed_at.desc())
        )
    ).all()
    for user_id, integrity in прохождения:
        if user_id not in заметки:
            note = integrity_note(integrity)
            if note:
                заметки[user_id] = note

    return LeaderboardResponse(
        class_id=school_class.id,
        class_name=school_class.name,
        rows=[
            LeaderboardRow(
                rank=index,
                student_id=student_id,
                full_name=full_name or "Без имени",
                level=level_of(xp),
                xp=xp,
                streak_days=streak,
                solved=solved,
                correct=correct,
                accuracy=round(correct / solved, 3) if solved else 0.0,
                test_done=tests > 0,
                integrity_note=заметки.get(student_id),
            )
            for index, (student_id, full_name, xp, streak, solved, correct, tests)
            in enumerate(rows, start=1)
        ],
    )


@router.post("/api/teacher/classes/{class_id}/assignments", response_model=AssignmentOut)
async def create_assignment(
    class_id: uuid.UUID,
    payload: CreateAssignmentRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AssignmentOut:
    """Выдать классу задание — набор предметов и размер пака."""
    teacher = _require_teacher(user)
    await _owned_class(session, teacher, class_id)

    assignment = ClassAssignment(
        class_id=class_id,
        teacher_id=teacher.id,
        title=payload.title.strip(),
        subjects=payload.subjects,
        size=payload.size,
        difficulty=payload.difficulty,
        due_date=payload.due_date,
    )
    session.add(assignment)
    await session.commit()
    await session.refresh(assignment)
    return AssignmentOut(**_assignment_fields(assignment), completed_by=0, students_total=0)


def _assignment_fields(assignment: ClassAssignment) -> dict:
    return {
        "id": assignment.id,
        "title": assignment.title,
        "subjects": list(assignment.subjects or []),
        "size": assignment.size,
        "difficulty": assignment.difficulty,
        "due_date": assignment.due_date,
        "created_at": assignment.created_at,
    }


@router.get("/api/teacher/classes/{class_id}/assignments", response_model=list[AssignmentOut])
async def list_assignments(
    class_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[AssignmentOut]:
    """Задания класса и сколько учеников за них уже брались."""
    teacher = _require_teacher(user)
    await _owned_class(session, teacher, class_id)

    assignments = (
        await session.scalars(
            select(ClassAssignment)
            .where(ClassAssignment.class_id == class_id)
            .order_by(ClassAssignment.created_at.desc())
        )
    ).all()
    students_total = await _students_count(session, class_id)

    result = []
    for assignment in assignments:
        # «взялся за задание» = решал задачи по его предметам после выдачи
        query = (
            select(func.count(func.distinct(TaskAttempt.user_id)))
            .join(User, User.id == TaskAttempt.user_id)
            .where(User.class_id == class_id, TaskAttempt.answered_at >= assignment.created_at)
        )
        if assignment.subjects:
            query = query.where(TaskAttempt.subject.in_(assignment.subjects))
        completed_by = await session.scalar(query) or 0
        result.append(
            AssignmentOut(
                **_assignment_fields(assignment),
                completed_by=completed_by,
                students_total=students_total,
            )
        )
    return result


@router.delete("/api/teacher/assignments/{assignment_id}")
async def delete_assignment(
    assignment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    teacher = _require_teacher(user)
    assignment = await session.get(ClassAssignment, assignment_id)
    if assignment is None or assignment.teacher_id != teacher.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Задание не найдено")
    await session.delete(assignment)
    await session.commit()
    return {"status": "deleted"}


@router.get("/api/classes/my-assignments", response_model=list[AssignmentOut])
async def my_assignments(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
) -> list[AssignmentOut]:
    """Задания класса — для ученика."""
    if user.class_id is None:
        return []
    assignments = (
        await session.scalars(
            select(ClassAssignment)
            .where(ClassAssignment.class_id == user.class_id)
            .order_by(ClassAssignment.created_at.desc())
            .limit(20)
        )
    ).all()
    return [AssignmentOut(**_assignment_fields(a)) for a in assignments]


@router.post("/api/classes/join", response_model=JoinClassResponse)
async def join_class(
    payload: JoinClassRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> JoinClassResponse:
    """Ученик вступает в класс по коду, полученному от педагога."""
    code = payload.join_code.strip().upper()
    school_class = await session.scalar(select(SchoolClass).where(SchoolClass.join_code == code))
    if school_class is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Код класса не найден — проверьте, что ввели верно")
    if user.role != UserRole.student:
        raise HTTPException(status.HTTP_409_CONFLICT, "В класс вступают ученики, а не педагоги")

    user.class_id = school_class.id
    user.school_class = school_class.name
    await session.commit()
    return JoinClassResponse(class_id=school_class.id, class_name=school_class.name)
