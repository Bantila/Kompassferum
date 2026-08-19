"""Банк вопросов и подсчёт результатов теста «Компас».

Три блока:
  A — интересы по типологии Голланда (6 типов × 2 вопроса, шкала 1–5);
  B — предметы (13 предметов × 3 знаниевых вопроса с правильным ответом + 1 вопрос интереса);
  C — soft skills (5 черт × 2 вопроса, шкала 1–5).

Ключевое отличие блока B: способности измеряются объективно — задачами с
правильным ответом, а не самооценкой. Самооценкой остаётся только интерес.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

QUESTIONS_PATH = Path(__file__).resolve().parent.parent / "tests_data" / "questions.json"

LIKERT_MIN, LIKERT_MAX = 1, 5

# Вес знаний против интереса в итоговом балле предмета.
# Знание весомее: это единственный объективный сигнал в блоке,
# интерес учитывается как модификатор мотивации.
KNOWLEDGE_WEIGHT = 0.65
INTEREST_WEIGHT = 0.35


class ScoringError(ValueError):
    """Ответы не удалось разобрать (неверный формат или значение вне шкалы)."""


@lru_cache
def load_questions() -> dict[str, Any]:
    """Банк вопросов целиком, включая correct_index. Кэшируется на процесс."""
    with QUESTIONS_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache
def _question_index() -> dict[str, dict[str, Any]]:
    """Плоский индекс id → вопрос по всем трём блокам."""
    data = load_questions()
    index: dict[str, dict[str, Any]] = {}
    for key in ("block_a_interests", "block_b_subjects", "block_c_softskills"):
        for question in data[key]:
            index[question["id"]] = question
    return index


def get_question(question_id: str) -> dict[str, Any] | None:
    return _question_index().get(question_id)


def public_questions(
    block: str | None = None, subject_group: str | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Вопросы для показа ученику — БЕЗ поля correct_index.

    Правильный ответ никогда не покидает бэкенд вместе с вопросом: иначе его
    видно в теле ответа API до того, как ученик выберет вариант. Проверка
    происходит в check_knowledge_answer() при приёме ответа.
    """
    data = load_questions()
    blocks = {
        "a": "block_a_interests",
        "b": "block_b_subjects",
        "c": "block_c_softskills",
    }
    if block is not None and block not in blocks:
        raise ScoringError(f"Неизвестный блок теста: {block!r}")

    wanted = [blocks[block]] if block else list(blocks.values())
    subjects: set[str] | None = None
    if subject_group is not None:
        groups = data["subject_groups"]
        if subject_group not in groups:
            raise ScoringError(f"Неизвестная группа предметов: {subject_group!r}")
        subjects = set(groups[subject_group])

    result: dict[str, list[dict[str, Any]]] = {}
    for key in wanted:
        items = []
        for question in data[key]:
            if subjects is not None and question.get("subject") not in subjects:
                continue
            items.append({k: v for k, v in question.items() if k != "correct_index"})
        result[key] = items
    return result


def check_knowledge_answer(question_id: str, selected_index: int) -> bool:
    """Проверка знаниевого вопроса на стороне бэкенда."""
    question = get_question(question_id)
    if question is None or question.get("type") != "knowledge":
        raise ScoringError(f"Знаниевый вопрос {question_id!r} не найден")
    return selected_index == question["correct_index"]


def _selected_index(answer: Any, question_id: str) -> int:
    """Ответ на знаниевый вопрос: либо число, либо объект с метаданными.

    Формат с объектом нужен, чтобы вместе с выбором сохранить время ответа —
    оно не влияет на MVP-скоринг, но пригодится для антифрод-анализа
    (слишком быстрый ответ на сложный вопрос — сигнал списывания/угадывания).
    """
    if isinstance(answer, bool):  # bool — подкласс int, ловим до int
        raise ScoringError(f"Ответ на {question_id!r} должен быть номером варианта")
    if isinstance(answer, int):
        return answer
    if isinstance(answer, dict) and "selected_index" in answer:
        value = answer["selected_index"]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ScoringError(f"selected_index в {question_id!r} должен быть числом")
        return value
    raise ScoringError(f"Не разобрать ответ на знаниевый вопрос {question_id!r}")


def _likert(answer: Any, question_id: str) -> float:
    """Ответ по шкале Лайкерта 1–5 (число либо {'value': n})."""
    if isinstance(answer, dict):
        answer = answer.get("value", answer.get("selected_index"))
    if isinstance(answer, bool) or not isinstance(answer, (int, float)):
        raise ScoringError(f"Ответ на {question_id!r} должен быть числом 1–5")
    if not LIKERT_MIN <= answer <= LIKERT_MAX:
        raise ScoringError(f"Ответ на {question_id!r} вне шкалы 1–5: {answer}")
    return float(answer)


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 2)


def knowledge_score(correct_count: int, total_questions: int) -> float:
    """Доля правильных ответов → шкала 1–5, линейно.

    0/3 → 1.0, 1/3 → 2.3, 2/3 → 3.7, 3/3 → 5.0
    (округление до десятых: 1 + 4 * correct / total).
    """
    if total_questions <= 0:
        raise ScoringError("total_questions должен быть > 0")
    return round(1 + 4 * correct_count / total_questions, 1)


def calculate_scores(answers: dict[str, Any]) -> dict[str, Any]:
    """Сырые ответы → агрегированный профиль ученика.

    Отвечать можно частями (тест из 74 вопросов проходится за несколько сессий):
    типы, черты и предметы, по которым ответов нет, в результат просто не попадают.
    """
    if not isinstance(answers, dict):
        raise ScoringError("answers должен быть словарём {question_id: answer}")

    index = _question_index()
    interests: dict[str, list[float]] = {}
    softskills: dict[str, list[float]] = {}
    # subject → {"correct": int, "total": int, "interest": float | None}
    subjects: dict[str, dict[str, Any]] = {}

    for question_id, answer in answers.items():
        question = index.get(question_id)
        if question is None:
            logger.warning("Неизвестный id вопроса в ответах: %s — пропущен", question_id)
            continue

        # блок определяем по полям самого вопроса, а не по префиксу id
        if "skill" in question:
            softskills.setdefault(question["skill"], []).append(_likert(answer, question_id))
        elif "subject" not in question:
            interests.setdefault(question["type"], []).append(_likert(answer, question_id))
        else:
            bucket = subjects.setdefault(
                question["subject"], {"correct": 0, "total": 0, "interest": None}
            )
            if question["type"] == "knowledge":
                bucket["total"] += 1
                if _selected_index(answer, question_id) == question["correct_index"]:
                    bucket["correct"] += 1
            else:
                bucket["interest"] = _likert(answer, question_id)

    subjects_out: dict[str, dict[str, Any]] = {}
    for subject, bucket in subjects.items():
        total = bucket["total"]
        interest = bucket["interest"]
        knowledge = knowledge_score(bucket["correct"], total) if total else None

        if knowledge is not None and interest is not None:
            subject_score = round(
                knowledge * KNOWLEDGE_WEIGHT + interest * INTEREST_WEIGHT, 3
            )
        else:
            # ответили только на часть предмета — берём то, что есть
            subject_score = knowledge if knowledge is not None else interest

        subjects_out[subject] = {
            "correct_count": bucket["correct"],
            "total_questions": total,
            "knowledge_score": knowledge,
            "interest": interest,
            "subject_score": subject_score,
        }

    return {
        "interests": {k: _mean(v) for k, v in interests.items()},
        "subjects": subjects_out,
        "softskills": {k: _mean(v) for k, v in softskills.items()},
    }


def completion_progress(answers: dict[str, Any]) -> dict[str, Any]:
    """Сколько вопросов пройдено — для сохранения прогресса между сессиями."""
    index = _question_index()
    answered = {qid for qid in answers if qid in index}
    return {
        "answered": len(answered),
        "total": len(index),
        "percent": round(100 * len(answered) / len(index), 1),
        "is_complete": len(answered) == len(index),
    }
