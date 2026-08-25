"""Подбор предметов для блока B: какие вопросы вообще имеет смысл задавать.

Спрашивать все 13 предметов — 52 вопроса, и до конца доходят не все. Но для
подбора профессий важны не все предметы, а те, что связаны со складом ученика.
Поэтому после блока A профиль интересов уходит в модель, и она называет пять
предметов, которые стоит проверить задачами. Блок B сокращается с 52 вопросов
до 15, весь тест — с 74 до 37.

Модель здесь не обязательна: если она недоступна, предметы выбираются по
таблице соответствий «тип Голланда — предметы». Подбор всегда возвращает пять
предметов, поэтому тест не может застрять.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.test_scoring import load_questions

logger = logging.getLogger(__name__)

SUBJECTS_IN_PLAN = 5

# Две задачи вместо трёх: пара различает три уровня — не решил ничего, знает
# базу, разбирается, — а третья стоила бы ученику лишней минуты.
#
# Пара меняется от попытки к попытке. Иначе повторное прохождение состоит из
# тех же самых задач (ученик помнит ответы, и замер ничего не стоит), а средние
# вопросы банка не задаются никогда — треть задач лежит мёртвым грузом.
#
# Первая попытка остаётся прежней парой: для большинства учеников тест
# выглядит ровно так же, как раньше.
DIFFICULTY_ROTATION = (
    ("easy", "hard"),
    ("medium", "hard"),
    ("easy", "medium"),
)


def difficulties_for_attempt(attempt: int) -> tuple[str, str]:
    """Пара сложностей для попытки №attempt (нумерация с нуля)."""
    return DIFFICULTY_ROTATION[max(attempt, 0) % len(DIFFICULTY_ROTATION)]

SUBJECT_CODES = tuple(load_questions()["subject_titles"])

# Запасная таблица: чем занят человек такого склада — те предметы и проверяем.
SUBJECTS_BY_TYPE: dict[str, list[str]] = {
    "realistic": ["physics", "informatics", "mathematics", "chemistry", "geography"],
    "investigative": ["mathematics", "physics", "informatics", "biology", "chemistry"],
    "artistic": ["arts_music", "literature", "russian", "foreign_language", "history"],
    "social": ["biology", "social_studies", "literature", "russian", "pe_safety"],
    "enterprising": ["social_studies", "mathematics", "foreign_language", "history", "russian"],
    "conventional": ["mathematics", "informatics", "social_studies", "geography", "russian"],
}

PLANNER_PROMPT = """Ты помогаешь подобрать школьнику 12–16 лет короткий тест по предметам.

На вход — профиль интересов по типологии Голланда, шкала 1–5:
realistic, investigative, artistic, social, enterprising, conventional.

Выбери ровно 5 школьных предметов, знания по которым стоит проверить задачами
именно у этого ученика. Опирайся на самые выраженные типы: предметы должны быть
связаны с профессиями, которые подходят такому складу.

Правила:
- предметы должны быть разными и покрывать разные области, а не пять смежных;
- если два типа выражены почти одинаково, возьми предметы под оба;
- для каждого предмета одним предложением объясни, почему он в списке."""


class SubjectChoice(BaseModel):
    """Один предмет в плане теста."""

    subject: Literal[SUBJECT_CODES] = Field(  # type: ignore[valid-type]
        description="Код школьного предмета из списка"
    )
    reason: str = Field(
        description="Одно предложение: почему этот предмет стоит проверить у этого ученика"
    )


class SubjectPlan(BaseModel):
    """План блока B: ровно пять разных предметов."""

    subjects: list[SubjectChoice] = Field(min_length=SUBJECTS_IN_PLAN, max_length=SUBJECTS_IN_PLAN)


# Сколько предметов берём у типов по убыванию выраженности. Ведущий тип даёт
# больше половины списка: если брать по одному от каждого из шести типов, у
# технаря и гуманитария получится почти один и тот же набор.
QUOTA_BY_RANK = (3, 2)


def fallback_plan(interests: dict[str, float]) -> list[str]:
    """Предметы по таблице соответствий — когда модель недоступна."""
    порядок = sorted(interests or {}, key=lambda k: interests[k], reverse=True)
    if not порядок:
        порядок = ["investigative"]

    выбранные: list[str] = []
    for ранг, квота in enumerate(QUOTA_BY_RANK):
        if ранг >= len(порядок):
            break
        добавлено = 0
        for код in SUBJECTS_BY_TYPE.get(порядок[ранг], []):
            if добавлено == квота or len(выбранные) == SUBJECTS_IN_PLAN:
                break
            if код not in выбранные:
                выбранные.append(код)
                добавлено += 1

    # квоты могли не набраться из-за пересечения таблиц — добираем по остальным
    # типам в том же порядке выраженности, затем чем угодно из банка
    for тип in порядок:
        for код in SUBJECTS_BY_TYPE.get(тип, []):
            if len(выбранные) == SUBJECTS_IN_PLAN:
                return выбранные
            if код not in выбранные:
                выбранные.append(код)
    for код in SUBJECT_CODES:
        if len(выбранные) == SUBJECTS_IN_PLAN:
            break
        if код not in выбранные:
            выбранные.append(код)
    return выбранные


async def _ask_gigachat(interests: dict[str, float]) -> list[str]:
    """Выбор предметов моделью. Схема не даёт назвать несуществующий предмет."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_gigachat import GigaChat

    settings = get_settings()
    model = GigaChat(
        credentials=settings.gigachat_credentials,
        scope=settings.gigachat_scope,
        model=settings.gigachat_model,
        base_url=settings.gigachat_base_url,
        verify_ssl_certs=settings.gigachat_verify_ssl,
        ca_bundle_file=settings.gigachat_ca_bundle or None,
        timeout=settings.openrouter_timeout_seconds,
        temperature=0.3,
    )
    structured = model.with_structured_output(SubjectPlan, method="json_schema", strict=True)

    plan: SubjectPlan = await structured.ainvoke(
        [
            SystemMessage(content=PLANNER_PROMPT),
            HumanMessage(content=json.dumps(interests, ensure_ascii=False)),
        ]
    )
    # Схема требует пять элементов, но не запрещает повтор одного предмета —
    # дубли убираем сами, иначе тест выродится в один предмет на 15 вопросов.
    выбранные: list[str] = []
    for choice in plan.subjects:
        if choice.subject not in выбранные:
            выбранные.append(choice.subject)
    return выбранные


async def plan_subjects(interests: dict[str, float]) -> dict[str, Any]:
    """Пять предметов для блока B. Исключения наружу не пробрасываются."""
    settings = get_settings()
    выбранные: list[str] = []
    источник = "fallback:rules"

    if settings.ai_provider.strip().lower() == "gigachat" and settings.gigachat_credentials:
        try:
            выбранные = await _ask_gigachat(interests)
            источник = settings.gigachat_model
        except Exception as exc:  # noqa: BLE001 — подбор не имеет права упасть
            logger.error("Планировщик: %s: %s", exc.__class__.__name__, exc)
            выбранные = []

    # модель могла вернуть меньше пяти после снятия дублей — добираем таблицей
    if len(выбранные) < SUBJECTS_IN_PLAN:
        if выбранные:
            logger.info("Планировщик: модель дала %s предметов, добираем таблицей", len(выбранные))
        for код in fallback_plan(interests):
            if len(выбранные) == SUBJECTS_IN_PLAN:
                break
            if код not in выбранные:
                выбранные.append(код)
        if источник != "fallback:rules":
            источник = f"{источник}+rules"

    return {
        "subjects": выбранные,
        "source": источник,
        "planned_by_model": источник != "fallback:rules",
    }


def questions_for_plan(subjects: list[str], attempt: int = 0) -> list[dict[str, Any]]:
    """Вопросы блока B по выбранным предметам, без правильных ответов.

    На предмет — две задачи и вопрос про интерес: пятнадцать вопросов вместо
    пятидесяти двух. Интерес оставляем, потому что итоговый балл предмета
    считается из знания и интереса вместе.

    Пара сложностей одна на все предметы прохождения: балл предмета — это доля
    верных ответов, сложность в него не входит, поэтому разные пары у разных
    предметов сделали бы предметы несравнимыми между собой. А ровно на этом
    сравнении строится совет, что подтягивать.
    """
    банк = load_questions()["block_b_subjects"]
    отобранные: list[dict[str, Any]] = []
    сложности = difficulties_for_attempt(attempt)

    for предмет in subjects:
        вопросы = [q for q in банк if q["subject"] == предмет]
        задачи = [q for q in вопросы if q["type"] == "knowledge"]
        for сложность in сложности:
            подходящие = [q for q in задачи if q.get("difficulty") == сложность]
            if подходящие:
                отобранные.append(подходящие[0])
        отобранные.extend(q for q in вопросы if q["type"] == "interest")

    return [{k: v for k, v in q.items() if k != "correct_index"} for q in отобранные]
