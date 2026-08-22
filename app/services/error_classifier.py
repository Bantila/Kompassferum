"""Классификация ошибки в ответе на задачу — 8 типов.

Перенесено из ErrorClassifier AI-Atlas. Работает без ИИ и без сети: ученик
получает разбор мгновенно, даже когда LLM недоступна. ИИ используется поверх —
чтобы объяснить ошибку словами, но тип и совет есть всегда.
"""

from __future__ import annotations

CORRECT = "correct"

ERROR_LABELS = {
    CORRECT: "Верно",
    "calculation": "Вычислительная ошибка",
    "sign": "Знаковая ошибка",
    "unit": "Ошибка единиц измерения",
    "attention": "Ошибка внимания",
    "conceptual": "Концептуальная ошибка",
    "methodology": "Методологическая ошибка",
    "incomplete": "Неполный ответ",
}

ERROR_RECOMMENDATIONS = {
    CORRECT: "Отличная работа! Продолжай в том же духе.",
    "calculation": "Метод верный, но сбой в арифметике. Считай на черновике и проверяй каждый шаг.",
    "sign": "Число верное, а знак — нет. При переносе через «=» знак меняется.",
    "unit": "Похоже на путаницу с единицами: переводи всё в одну систему до решения.",
    "attention": "Ты почти попал — читай условие медленнее и выделяй ключевые данные.",
    "conceptual": "Стоит повторить теорию по этой теме и разобрать примеры из учебника.",
    "methodology": "Разбери алгоритм решения таких задач по шагам и запомни порядок.",
    "incomplete": "Ответ неполный — перечитай вопрос и ответь развёрнуто.",
}

# для этих предметов непохожий ответ вероятнее означает сбитый алгоритм решения,
# а не пробел в понятиях: там есть чёткий порядок действий
EXACT_SUBJECTS = {"mathematics", "physics", "chemistry", "informatics"}

# типичные множители при путанице в единицах (км/м, г/кг и т.п.)
UNIT_RATIOS = (10.0, 100.0, 1000.0, 0.1, 0.01, 0.001)

ATTENTION_SIMILARITY = 0.75


def _to_number(value: str) -> float | None:
    try:
        return float(value.replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def _jaccard(a: str, b: str) -> float:
    set_a, set_b = set(a), set(b)
    union = set_a | set_b
    return len(set_a & set_b) / len(union) if union else 0.0


def _result(error_type: str, confidence: float) -> dict:
    return {
        "error_type": error_type,
        "error_label": ERROR_LABELS.get(error_type, error_type),
        "confidence": round(confidence, 2),
        "recommendation": ERROR_RECOMMENDATIONS.get(error_type, "Повтори тему и попробуй снова."),
        "is_correct": error_type == CORRECT,
    }


def classify(user_answer: str, correct_answer: str, subject: str = "") -> dict:
    """Определить тип ошибки по ответу ученика."""
    given = (user_answer or "").strip()
    expected = (correct_answer or "").strip()

    if given.casefold() == expected.casefold():
        return _result(CORRECT, 1.0)
    if not given:
        return _result("incomplete", 0.95)

    given_num, expected_num = _to_number(given), _to_number(expected)
    # короткий нечисловой огрызок против развёрнутого ответа — это «не дописал».
    # Проверяем ПОСЛЕ разбора чисел: «3» против «-3» — полноценный ответ со знаком,
    # а не обрывок (в оригинале AI-Atlas такие ответы ошибочно считались неполными)
    if given_num is None and len(given) < 2 and len(expected) > 3:
        return _result("incomplete", 0.9)
    if given_num is not None and expected_num is not None:
        if abs(given_num) == abs(expected_num) and given_num * expected_num < 0:
            return _result("sign", 0.97)
        if expected_num != 0:
            ratio = given_num / expected_num
            if any(abs(ratio - r) < 0.01 for r in UNIT_RATIOS):
                return _result("unit", 0.90)
            diff = abs(given_num - expected_num) / abs(expected_num)
            if 0 < diff < 0.30:
                # чем ближе к правильному, тем увереннее, что это просто счёт
                return _result("calculation", max(0.70, 0.95 - diff))
            if diff >= 0.30:
                return _result("conceptual", 0.80)

    similarity = _jaccard(given.casefold(), expected.casefold())
    if similarity > ATTENTION_SIMILARITY:
        return _result("attention", similarity)
    if subject in EXACT_SUBJECTS:
        return _result("methodology", 0.75)
    return _result("conceptual", 0.70)
