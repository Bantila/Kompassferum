"""Банк тренировочных задач и сборка персонального пака.

Пак собирается по предметам, которые «Компас» назвал слабыми для подходящих
профессий — так рекомендация перестаёт быть тупиком: ученику сразу есть что
решать именно по тем предметам, которых не хватает.

Правильный ответ наружу не отдаётся: проверка идёт на бэкенде, как и в тесте.
"""

from __future__ import annotations

import random
from functools import lru_cache
from pathlib import Path
from typing import Any
import json

TASKS_PATH = Path(__file__).resolve().parent.parent / "tests_data" / "tasks.json"

DIFFICULTY_ORDER = ("easy", "medium", "hard")
DEFAULT_PACK_SIZE = 5


@lru_cache
def load_tasks() -> dict[str, Any]:
    with TASKS_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache
def _by_id() -> dict[str, dict[str, Any]]:
    return {task["id"]: task for task in load_tasks()["tasks"]}


@lru_cache
def _by_subject() -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for task in load_tasks()["tasks"]:
        grouped.setdefault(task["subject"], []).append(task)
    return grouped


def available_subjects() -> list[str]:
    return sorted(_by_subject())


def get_task(task_id: str) -> dict[str, Any] | None:
    return _by_id().get(task_id)


def public_task(task: dict[str, Any]) -> dict[str, Any]:
    """Задача для показа ученику — без ответа и пояснения."""
    return {k: v for k, v in task.items() if k not in ("answer", "explanation")}


def build_pack(
    subjects: list[str] | None = None,
    size: int = DEFAULT_PACK_SIZE,
    difficulty: str | None = None,
    exclude_ids: set[str] | None = None,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """Собрать пак задач: поровну по предметам, от простых к сложным.

    subjects — предметы, которые ученику стоит подтянуть; если не заданы,
    берём весь банк.
    """
    grouped = _by_subject()
    wanted = [s for s in (subjects or []) if s in grouped] or list(grouped)
    exclude = exclude_ids or set()
    rng = random.Random(seed)

    pool_by_subject = {
        subject: [
            task
            for task in grouped[subject]
            if task["id"] not in exclude and (difficulty is None or task["difficulty"] == difficulty)
        ]
        for subject in wanted
    }
    for tasks in pool_by_subject.values():
        rng.shuffle(tasks)

    # берём по кругу, чтобы предметы в паке чередовались, а не шли блоком
    picked: list[dict[str, Any]] = []
    while len(picked) < size and any(pool_by_subject.values()):
        for subject in wanted:
            if len(picked) >= size:
                break
            if pool_by_subject.get(subject):
                picked.append(pool_by_subject[subject].pop())

    picked.sort(key=lambda t: DIFFICULTY_ORDER.index(t["difficulty"])
                if t["difficulty"] in DIFFICULTY_ORDER else 1)
    return picked
