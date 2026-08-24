"""Проверка того, насколько ответам можно доверять.

Тест из 37 вопросов легко «прокликать»: выбрать один вариант везде или
пролистать задачи быстрее, чем их можно прочитать. Такой результат выглядит
как настоящий, и педагог принимает решения по цифрам, за которыми ничего нет.

Здесь считаются признаки, по которым это видно, и общий уровень доверия.
Никаких обвинений и блокировок: ученик получает свои рекомендации в любом
случае, а педагог видит пометку, что цифрам верить не стоит.

Все признаки — эвристики. Быстрый ответ бывает у того, кто знает предмет,
а одинаковые ответы в шкале — у человека с ровным профилем. Поэтому один
признак ничего не решает: вердикт выносится по их сумме.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.test_scoring import load_questions

logger = logging.getLogger(__name__)

# Меньше трёх секунд на задачу — её не успеть прочитать, не то что решить.
# Вопросы шкалы («насколько это про тебя») отвечаются быстрее, для них порог ниже.
MIN_SECONDS_KNOWLEDGE = 3.0
MIN_SECONDS_SCALE = 1.0

# Доли, начиная с которых признак считается сработавшим.
RUSHED_SHARE = 0.4          # почти половина ответов быстрее порога
SAME_OPTION_SHARE = 0.8     # один и тот же вариант почти везде
STRAIGHT_LINE_SHARE = 0.9   # одна и та же оценка во всей шкале

TRUST_THRESHOLDS = (
    (0.7, "low"),
    (0.35, "medium"),
)


def _answer_parts(answer: Any) -> tuple[Any, float | None]:
    """Значение ответа и время на него: клиент шлёт либо число, либо объект."""
    if isinstance(answer, dict):
        значение = answer.get("selected_index", answer.get("value"))
        время = answer.get("time_spent_seconds")
        return значение, float(время) if isinstance(время, (int, float)) else None
    return answer, None


def check(raw_answers: dict[str, Any]) -> dict[str, Any]:
    """Сырые ответы → уровень доверия и сработавшие признаки."""
    if not isinstance(raw_answers, dict) or not raw_answers:
        return {"trust": "unknown", "score": 0.0, "flags": [], "measured": 0}

    index = {
        q["id"]: q
        for key in ("block_a_interests", "block_b_subjects", "block_c_softskills")
        for q in load_questions()[key]
    }

    задачи: list[tuple[Any, float | None]] = []
    шкалы: list[tuple[Any, float | None]] = []
    for id_вопроса, ответ in raw_answers.items():
        вопрос = index.get(id_вопроса)
        if вопрос is None:
            continue
        (задачи if вопрос.get("type") == "knowledge" else шкалы).append(_answer_parts(ответ))

    flags: list[dict[str, Any]] = []
    измерено = 0

    # 1. Ответы быстрее, чем вопрос можно прочитать.
    быстрых, со_временем = 0, 0
    for значения, порог in ((задачи, MIN_SECONDS_KNOWLEDGE), (шкалы, MIN_SECONDS_SCALE)):
        for _, время in значения:
            if время is None:
                continue
            со_временем += 1
            if время < порог:
                быстрых += 1
    if со_временем:
        измерено += 1
        доля = быстрых / со_временем
        if доля >= RUSHED_SHARE:
            flags.append({
                "code": "rushed",
                "share": round(доля, 2),
                "detail": f"{быстрых} из {со_временем} ответов быстрее, чем вопрос можно прочитать",
            })

    # 2. Один и тот же вариант в задачах: признак прокликивания, а не знания.
    варианты = [значение for значение, _ in задачи if значение is not None]
    if len(варианты) >= 5:
        измерено += 1
        доля = max(варианты.count(v) for v in set(варианты)) / len(варианты)
        if доля >= SAME_OPTION_SHARE:
            flags.append({
                "code": "same_option",
                "share": round(доля, 2),
                "detail": "почти во всех задачах выбран один и тот же по счёту вариант",
            })

    # 3. Прямая линия в шкалах: одна оценка на все утверждения о себе.
    оценки = [значение for значение, _ in шкалы if isinstance(значение, (int, float))]
    if len(оценки) >= 8:
        измерено += 1
        доля = max(оценки.count(v) for v in set(оценки)) / len(оценки)
        if доля >= STRAIGHT_LINE_SHARE:
            flags.append({
                "code": "straight_line",
                "share": round(доля, 2),
                "detail": "почти на все утверждения о себе дана одна и та же оценка",
            })

    # Доверие падает по сумме признаков: каждый в отдельности бывает и у
    # честного ученика, а вот два сразу — уже почти наверняка прокликивание.
    score = round(min(1.0, sum(f["share"] for f in flags) / 2), 2)
    trust = "high"
    for порог, уровень in TRUST_THRESHOLDS:
        if score >= порог:
            trust = уровень
            break

    if flags:
        logger.info("Проверка ответов: доверие %s, признаки %s", trust, [f["code"] for f in flags])

    return {"trust": trust, "score": score, "flags": flags, "measured": измерено}


def summary_line(integrity: dict[str, Any] | None) -> str | None:
    """Короткая формулировка для педагога — без обвинений."""
    if not integrity or integrity.get("trust") in (None, "high", "unknown"):
        return None
    if integrity["trust"] == "low":
        return "Ответы похожи на случайные — результат стоит перепроверить"
    return "Часть ответов дана слишком быстро — результат может быть неточным"
