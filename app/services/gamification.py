"""XP, уровни, серии дней и достижения.

Перенесено из AchievementService/TaskService AI-Atlas. Начисление идёт и за
неверный ответ (меньше): ученик, который разбирает ошибки, тоже движется вперёд —
иначе тренажёр наказывает за попытки и в него перестают заходить.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TaskAttempt, UserAchievement, UserStats

XP_CORRECT = 10
XP_WRONG = 2
XP_PER_LEVEL = 100

# код → иконка, название, условие, редкость
ACHIEVEMENTS: dict[str, dict[str, str]] = {
    "first_task": {"icon": "🎯", "title": "Первый шаг", "hint": "Реши первую задачу", "rarity": "common"},
    "tasks_10": {"icon": "📚", "title": "Любознательный", "hint": "Реши 10 задач", "rarity": "common"},
    "tasks_50": {"icon": "🔥", "title": "Упорный", "hint": "Реши 50 задач", "rarity": "rare"},
    "tasks_100": {"icon": "💯", "title": "Сотня", "hint": "Реши 100 задач", "rarity": "rare"},
    "tasks_500": {"icon": "🏆", "title": "Легенда", "hint": "Реши 500 задач", "rarity": "epic"},
    "perfect_5": {"icon": "✨", "title": "Без ошибок", "hint": "5 задач подряд без ошибок", "rarity": "common"},
    "accuracy_80": {"icon": "🎓", "title": "Отличник", "hint": "Точность выше 80%", "rarity": "rare"},
    "accuracy_95": {"icon": "💎", "title": "Перфекционист", "hint": "Точность выше 95%", "rarity": "epic"},
    "streak_3": {"icon": "📅", "title": "Три дня подряд", "hint": "Занимайся 3 дня подряд", "rarity": "common"},
    "streak_7": {"icon": "🗓️", "title": "Неделя", "hint": "Занимайся 7 дней подряд", "rarity": "rare"},
    "streak_30": {"icon": "🌟", "title": "Месяц", "hint": "Занимайся 30 дней подряд", "rarity": "epic"},
    "subj_master": {"icon": "🏅", "title": "Мастер предмета", "hint": "20 задач по одному предмету", "rarity": "rare"},
    "all_subjects": {"icon": "🌈", "title": "Разносторонний", "hint": "Задачи по всем предметам", "rarity": "epic"},
    "level_5": {"icon": "⬆️", "title": "Уровень 5", "hint": "Достигни 5 уровня", "rarity": "common"},
    "level_10": {"icon": "🚀", "title": "Уровень 10", "hint": "Достигни 10 уровня", "rarity": "rare"},
    "level_20": {"icon": "👑", "title": "Элита", "hint": "Достигни 20 уровня", "rarity": "epic"},
    "night_owl": {"icon": "🦉", "title": "Сова", "hint": "Реши задачу после 22:00", "rarity": "common"},
    "early_bird": {"icon": "🌅", "title": "Жаворонок", "hint": "Реши задачу до 7:00", "rarity": "common"},
}

TOTAL_SUBJECTS = 8  # столько предметов в банке задач


def level_of(xp: int) -> int:
    """Уровень по опыту: 0–99 XP — первый уровень, дальше по сотне."""
    return xp // XP_PER_LEVEL + 1


def level_progress(xp: int) -> dict[str, int]:
    """Сколько XP набрано внутри текущего уровня и сколько нужно до следующего."""
    return {
        "level": level_of(xp),
        "xp": xp,
        "xp_in_level": xp % XP_PER_LEVEL,
        "xp_to_next": XP_PER_LEVEL - (xp % XP_PER_LEVEL),
        "xp_per_level": XP_PER_LEVEL,
    }


async def _get_or_create_stats(session: AsyncSession, user_id) -> UserStats:
    stats = await session.get(UserStats, user_id)
    if stats is None:
        stats = UserStats(user_id=user_id)
        session.add(stats)
        await session.flush()
    return stats


async def _earned_codes(session: AsyncSession, user_id) -> set[str]:
    rows = await session.scalars(
        select(UserAchievement.code).where(UserAchievement.user_id == user_id)
    )
    return set(rows.all())


async def _check_achievements(
    session: AsyncSession, user_id, stats: UserStats, answered_at
) -> list[dict[str, Any]]:
    """Выдать все достижения, условия которых уже выполнены."""
    total, correct = (
        await session.execute(
            select(
                func.count(TaskAttempt.id),
                func.count(TaskAttempt.id).filter(TaskAttempt.is_correct.is_(True)),
            ).where(TaskAttempt.user_id == user_id)
        )
    ).one()
    accuracy = correct / total if total else 0.0
    level = level_of(stats.xp)

    earned = await _earned_codes(session, user_id)
    unlocked: list[str] = []

    def unlock(code: str, condition: bool) -> None:
        if condition and code not in earned:
            unlocked.append(code)

    unlock("first_task", total >= 1)
    unlock("tasks_10", total >= 10)
    unlock("tasks_50", total >= 50)
    unlock("tasks_100", total >= 100)
    unlock("tasks_500", total >= 500)
    unlock("accuracy_80", total >= 10 and accuracy >= 0.80)
    unlock("accuracy_95", total >= 20 and accuracy >= 0.95)
    unlock("streak_3", stats.streak_days >= 3)
    unlock("streak_7", stats.streak_days >= 7)
    unlock("streak_30", stats.streak_days >= 30)
    unlock("level_5", level >= 5)
    unlock("level_10", level >= 10)
    unlock("level_20", level >= 20)
    unlock("night_owl", answered_at.hour >= 22)
    unlock("early_bird", answered_at.hour < 7)

    # пять последних попыток без единой ошибки
    last_five = (
        await session.scalars(
            select(TaskAttempt.is_correct)
            .where(TaskAttempt.user_id == user_id)
            .order_by(TaskAttempt.answered_at.desc())
            .limit(5)
        )
    ).all()
    unlock("perfect_5", len(last_five) == 5 and all(last_five))

    per_subject = (
        await session.execute(
            select(TaskAttempt.subject, func.count(TaskAttempt.id))
            .where(TaskAttempt.user_id == user_id)
            .group_by(TaskAttempt.subject)
        )
    ).all()
    unlock("subj_master", any(count >= 20 for _, count in per_subject))
    unlock("all_subjects", len(per_subject) >= TOTAL_SUBJECTS)

    for code in unlocked:
        session.add(UserAchievement(user_id=user_id, code=code))
    return [{"code": code, **ACHIEVEMENTS[code]} for code in unlocked]


async def register_answer(
    session: AsyncSession, user_id, is_correct: bool, answered_at
) -> dict[str, Any]:
    """Начислить XP, обновить серию дней и выдать достижения.

    Возвращает то, что показать ученику сразу после ответа.
    """
    stats = await _get_or_create_stats(session, user_id)
    level_before = level_of(stats.xp)

    xp_earned = XP_CORRECT if is_correct else XP_WRONG
    stats.xp += xp_earned

    today = answered_at.date()
    if stats.last_activity_date != today:
        # занимался вчера — серия продолжается, иначе начинается заново
        stats.streak_days = (
            stats.streak_days + 1 if stats.last_activity_date == today - timedelta(days=1) else 1
        )
        stats.best_streak = max(stats.best_streak, stats.streak_days)
        stats.last_activity_date = today

    await session.flush()
    new_achievements = await _check_achievements(session, user_id, stats, answered_at)

    return {
        "xp_earned": xp_earned,
        "xp_total": stats.xp,
        "level": level_of(stats.xp),
        "level_up": level_of(stats.xp) > level_before,
        "streak_days": stats.streak_days,
        "new_achievements": new_achievements,
    }


async def progress_summary(session: AsyncSession, user_id) -> dict[str, Any]:
    """Полная сводка прогресса для экрана профиля."""
    stats = await session.get(UserStats, user_id)
    xp = stats.xp if stats else 0
    streak = stats.streak_days if stats else 0
    best = stats.best_streak if stats else 0

    total, correct = (
        await session.execute(
            select(
                func.count(TaskAttempt.id),
                func.count(TaskAttempt.id).filter(TaskAttempt.is_correct.is_(True)),
            ).where(TaskAttempt.user_id == user_id)
        )
    ).one()

    earned = await _earned_codes(session, user_id)
    return {
        **level_progress(xp),
        "streak_days": streak,
        "best_streak": best,
        "total_tasks": total,
        "correct_tasks": correct,
        "accuracy": round(correct / total, 3) if total else 0.0,
        "achievements": [
            {"code": code, **meta, "earned": code in earned}
            for code, meta in ACHIEVEMENTS.items()
        ],
        "earned_count": len(earned),
        "total_achievements": len(ACHIEVEMENTS),
    }
