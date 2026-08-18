"""Тесты подсчёта результатов теста."""

from __future__ import annotations

import pytest

from app.services.test_scoring import (
    ScoringError,
    calculate_scores,
    check_knowledge_answer,
    completion_progress,
    knowledge_score,
    load_questions,
    public_questions,
)


def test_bank_has_74_questions() -> None:
    data = load_questions()
    assert len(data["block_a_interests"]) == 12
    assert len(data["block_b_subjects"]) == 52
    assert len(data["block_c_softskills"]) == 10
    subjects = {q["subject"] for q in data["block_b_subjects"]}
    assert len(subjects) == 13
    # на каждый предмет — ровно 3 знаниевых вопроса и ровно 1 про интерес
    for subject in subjects:
        block = [q for q in data["block_b_subjects"] if q["subject"] == subject]
        assert sum(q["type"] == "knowledge" for q in block) == 3
        assert sum(q["type"] == "interest" for q in block) == 1
        # три разных уровня сложности
        assert {q["difficulty"] for q in block if q["type"] == "knowledge"} == {
            "easy",
            "medium",
            "hard",
        }


def test_correct_index_never_leaves_backend() -> None:
    """Правильный ответ не должен уезжать вместе с вопросом."""
    questions = public_questions()
    for block in questions.values():
        for question in block:
            assert "correct_index" not in question
    # но внутри бэкенда он есть и проверка работает
    assert check_knowledge_answer("b1_k1", 1) is True
    assert check_knowledge_answer("b1_k1", 0) is False


@pytest.mark.parametrize(
    ("correct", "expected"),
    [(0, 1.0), (1, 2.3), (2, 3.7), (3, 5.0)],
)
def test_knowledge_score_scale(correct: int, expected: float) -> None:
    assert knowledge_score(correct, 3) == expected


def test_subject_score_matches_spec_example() -> None:
    """Пример из ТЗ: 2/3 по математике при интересе 4.5 → 3.98."""
    scores = calculate_scores(
        {
            "b1_k1": 1,  # верно
            "b1_k2": 0,  # верно
            "b1_k3": 2,  # неверно
            "b1_interest": 4.5,
            "b2_k1": 1,  # верно
            "b2_k2": 3,  # неверно
            "b2_k3": 3,  # неверно
            "b2_interest": 3,
        }
    )
    math = scores["subjects"]["mathematics"]
    assert math["correct_count"] == 2
    assert math["knowledge_score"] == 3.7
    assert math["subject_score"] == 3.98

    physics = scores["subjects"]["physics"]
    assert physics["knowledge_score"] == 2.3
    assert physics["subject_score"] == 2.545


def test_knowledge_is_objective_not_self_assessment() -> None:
    """Высокий интерес не должен вытягивать нулевое знание в топ."""
    scores = calculate_scores(
        {"b1_k1": 3, "b1_k2": 3, "b1_k3": 3, "b1_interest": 5}  # все три мимо
    )
    math = scores["subjects"]["mathematics"]
    assert math["correct_count"] == 0
    assert math["knowledge_score"] == 1.0
    assert math["subject_score"] == 2.4  # 1*0.65 + 5*0.35


def test_pairs_are_averaged() -> None:
    scores = calculate_scores({"a1": 5, "a2": 2, "c1": 4, "c2": 3})
    assert scores["interests"]["realistic"] == 3.5
    assert scores["softskills"]["teamwork"] == 3.5


def test_answer_with_time_metadata_is_accepted() -> None:
    """Формат с временем ответа — задел на антифрод, скоринг не ломает."""
    scores = calculate_scores(
        {"b1_k1": {"selected_index": 1, "time_spent_seconds": 0.4}}
    )
    assert scores["subjects"]["mathematics"]["correct_count"] == 1


def test_partial_answers_do_not_invent_blocks() -> None:
    """Тест проходится за несколько сессий — неотвеченного в профиле быть не должно."""
    scores = calculate_scores({"a1": 4, "a2": 4})
    assert scores["interests"] == {"realistic": 4.0}
    assert scores["subjects"] == {}
    assert scores["softskills"] == {}


def test_unknown_question_id_is_ignored() -> None:
    assert calculate_scores({"нет_такого": 3})["interests"] == {}


@pytest.mark.parametrize("bad", [{"a1": 0}, {"a1": 6}, {"a1": "четыре"}, {"a1": True}])
def test_out_of_scale_answer_raises(bad: dict) -> None:
    with pytest.raises(ScoringError):
        calculate_scores(bad)


def test_completion_progress(full_answers: dict) -> None:
    assert completion_progress({}) == {
        "answered": 0,
        "total": 74,
        "percent": 0.0,
        "is_complete": False,
    }
    assert completion_progress(full_answers)["is_complete"] is True


def test_subject_group_filter() -> None:
    exact = public_questions(block="b", subject_group="exact")["block_b_subjects"]
    assert {q["subject"] for q in exact} == {
        "mathematics",
        "physics",
        "chemistry",
        "informatics",
    }
    with pytest.raises(ScoringError):
        public_questions(subject_group="нет_такой_группы")
