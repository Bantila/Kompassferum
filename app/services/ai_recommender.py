"""Подбор профессий через OpenRouter + rule-based запасной вариант.

Наружу торчит одна функция — recommend_professions(). Она никогда не бросает
исключение из-за проблем с LLM: любой сбой сети, таймаут, кривой JSON или
не-200 от OpenRouter приводят к rule-based ответу с флагом fallback=True.
Это требование критерия «Стабильность и отклик»: демо не должно падать
из-за чужого API.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.config import get_settings
from app.services.test_scoring import load_questions

logger = logging.getLogger(__name__)

FALLBACK_MODEL_NAME = "fallback:rule-based"

SYSTEM_PROMPT = """Ты — профориентационный ассистент «Компас» для российских школьников 12–16 лет.

На вход ты получаешь JSON с результатами психометрического теста ученика:
- interests — выраженность 6 типов по Голланду (realistic, investigative, artistic, social, enterprising, conventional), шкала 1–5;
- subjects — по каждому школьному предмету: knowledge_score (объективный результат задач, 1–5), interest (самооценка интереса, 1–5), subject_score (итог);
- softskills — teamwork, leadership, creativity, analytical, resilience, шкала 1–5.

Подбери ровно 5 профессий, подходящих этому ученику.

Правила:
- Обоснование каждой профессии — 2–3 предложения, обязательно опирайся на КОНКРЕТНЫЕ баллы из профиля и называй их (например: «твой investigative 4.6 и знание физики 5.0»).
- Обращайся к ученику на «ты», пиши просто и по-доброму, без канцелярита и без обещаний «ты точно станешь».
- Не выдумывай баллы, которых нет в профиле.
- Предметы для подтягивания выбирай из тех, что реально нужны профессии и где у ученика балл ниже.
- category — одно из: технологии, наука, творчество, услуги, менеджмент, медицина, образование.

Ответ верни СТРОГО валидным JSON без markdown-обёртки, без ``` и без пояснений до или после:
{
  "professions": [
    {
      "name": "название профессии",
      "reasoning": "2–3 предложения с опорой на баллы",
      "subjects_to_improve": ["математика", "физика"],
      "category": "технологии"
    }
  ]
}
Ровно 5 элементов в массиве professions."""

# По одной профессии-заглушке на каждый тип Голланда — используется,
# когда LLM недоступна.
FALLBACK_PROFESSIONS: dict[str, list[dict[str, Any]]] = {
    "realistic": [
        {"name": "Инженер-механик", "category": "технологии",
         "subjects_to_improve": ["математика", "физика"]},
        {"name": "Специалист по робототехнике", "category": "технологии",
         "subjects_to_improve": ["физика", "информатика"]},
        {"name": "Автомеханик-диагност", "category": "услуги",
         "subjects_to_improve": ["физика", "информатика"]},
        {"name": "Технолог производства", "category": "технологии",
         "subjects_to_improve": ["химия", "математика"]},
        {"name": "Пилот / оператор БПЛА", "category": "технологии",
         "subjects_to_improve": ["физика", "география"]},
    ],
    "investigative": [
        {"name": "Аналитик данных", "category": "технологии",
         "subjects_to_improve": ["математика", "информатика"]},
        {"name": "Учёный-исследователь", "category": "наука",
         "subjects_to_improve": ["физика", "математика"]},
        {"name": "Биотехнолог", "category": "наука",
         "subjects_to_improve": ["биология", "химия"]},
        {"name": "Врач-диагност", "category": "медицина",
         "subjects_to_improve": ["биология", "химия"]},
        {"name": "Программист", "category": "технологии",
         "subjects_to_improve": ["информатика", "математика"]},
    ],
    "artistic": [
        {"name": "Дизайнер интерфейсов", "category": "творчество",
         "subjects_to_improve": ["ИЗО и музыка", "информатика"]},
        {"name": "Режиссёр монтажа", "category": "творчество",
         "subjects_to_improve": ["литература", "ИЗО и музыка"]},
        {"name": "Иллюстратор", "category": "творчество",
         "subjects_to_improve": ["ИЗО и музыка", "история"]},
        {"name": "Копирайтер", "category": "творчество",
         "subjects_to_improve": ["русский язык", "литература"]},
        {"name": "Архитектор", "category": "творчество",
         "subjects_to_improve": ["математика", "ИЗО и музыка"]},
    ],
    "social": [
        {"name": "Учитель", "category": "образование",
         "subjects_to_improve": ["обществознание", "русский язык"]},
        {"name": "Психолог", "category": "услуги",
         "subjects_to_improve": ["биология", "обществознание"]},
        {"name": "Врач общей практики", "category": "медицина",
         "subjects_to_improve": ["биология", "химия"]},
        {"name": "Социальный работник", "category": "услуги",
         "subjects_to_improve": ["обществознание", "литература"]},
        {"name": "HR-специалист", "category": "менеджмент",
         "subjects_to_improve": ["обществознание", "английский язык"]},
    ],
    "enterprising": [
        {"name": "Предприниматель", "category": "менеджмент",
         "subjects_to_improve": ["обществознание", "математика"]},
        {"name": "Маркетолог", "category": "менеджмент",
         "subjects_to_improve": ["обществознание", "информатика"]},
        {"name": "Продакт-менеджер", "category": "менеджмент",
         "subjects_to_improve": ["информатика", "английский язык"]},
        {"name": "Юрист", "category": "услуги",
         "subjects_to_improve": ["обществознание", "русский язык"]},
        {"name": "Event-менеджер", "category": "менеджмент",
         "subjects_to_improve": ["обществознание", "английский язык"]},
    ],
    "conventional": [
        {"name": "Бухгалтер", "category": "услуги",
         "subjects_to_improve": ["математика", "обществознание"]},
        {"name": "Финансовый аналитик", "category": "менеджмент",
         "subjects_to_improve": ["математика", "обществознание"]},
        {"name": "Специалист по логистике", "category": "услуги",
         "subjects_to_improve": ["география", "математика"]},
        {"name": "Администратор баз данных", "category": "технологии",
         "subjects_to_improve": ["информатика", "математика"]},
        {"name": "Специалист по документообороту", "category": "услуги",
         "subjects_to_improve": ["русский язык", "информатика"]},
    ],
}

_TYPE_LABELS = {
    "realistic": "практический (тебе нравится делать руками и разбираться в технике)",
    "investigative": "исследовательский (тебе нравится докапываться до сути)",
    "artistic": "творческий (тебе важно создавать своё и делать это красиво)",
    "social": "социальный (тебе нравится помогать людям и объяснять)",
    "enterprising": "предпринимательский (тебе нравится организовывать и убеждать)",
    "conventional": "организованный (тебе нравится порядок, данные и чёткий план)",
}

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_markdown_fence(content: str) -> str:
    """Модели любят оборачивать JSON в ```json ... ``` — снимаем обёртку."""
    cleaned = _JSON_FENCE_RE.sub("", content.strip()).strip()
    # если вокруг JSON остался текст — берём кусок от первой { до последней }
    if not cleaned.startswith("{"):
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            cleaned = cleaned[start : end + 1]
    return cleaned


STRONG_SUBJECT_THRESHOLD = 4.0


def _strong_subjects(scores: dict[str, Any]) -> set[str]:
    """Предметы, которые ученику подтягивать не нужно — он и так их знает."""
    titles = load_questions()["subject_titles"]
    strong = set()
    for code, data in (scores.get("subjects") or {}).items():
        score = data.get("subject_score") if isinstance(data, dict) else None
        if score is not None and score >= STRONG_SUBJECT_THRESHOLD:
            strong.add(titles.get(code, code).lower())
    return strong


def build_fallback(scores: dict[str, Any]) -> dict[str, Any]:
    """Rule-based подбор по самому выраженному типу Голланда."""
    interests = scores.get("interests") or {}
    if interests:
        top_type = max(interests, key=lambda k: interests[k])
    else:
        top_type = "investigative"
    top_score = interests.get(top_type)

    label = _TYPE_LABELS.get(top_type, top_type)
    strong = _strong_subjects(scores)
    professions = []
    for item in FALLBACK_PROFESSIONS.get(top_type, FALLBACK_PROFESSIONS["investigative"]):
        score_hint = f" (балл {top_score})" if top_score is not None else ""
        professions.append(
            {
                **item,
                # не советуем подтягивать то, что ученик и так знает на 4+
                "subjects_to_improve": [
                    subject
                    for subject in item["subjects_to_improve"]
                    if subject.lower() not in strong
                ],
                "reasoning": (
                    f"У тебя ярче всего выражен {label}{score_hint}. "
                    f"Профессия «{item['name']}» опирается именно на этот склад. "
                    "Это подборка упрощённым алгоритмом — пройди тест ещё раз "
                    "чуть позже, чтобы получить разбор от ИИ."
                ),
            }
        )
    return {
        "professions": professions,
        "fallback": True,
        "fallback_reason": "llm_unavailable",
        "top_interest": top_type,
    }


def _validate_professions(payload: Any) -> list[dict[str, Any]]:
    """Ответ LLM → список профессий. Бросает ValueError, если структура не та."""
    if not isinstance(payload, dict):
        raise ValueError("ответ LLM — не JSON-объект")
    professions = payload.get("professions")
    if not isinstance(professions, list) or not professions:
        raise ValueError("в ответе LLM нет непустого списка professions")

    result = []
    for item in professions[:5]:
        if not isinstance(item, dict) or not item.get("name"):
            raise ValueError("элемент professions без поля name")
        subjects = item.get("subjects_to_improve") or []
        result.append(
            {
                "name": str(item["name"]),
                "reasoning": str(item.get("reasoning", "")),
                "subjects_to_improve": [str(s) for s in subjects]
                if isinstance(subjects, list)
                else [str(subjects)],
                "category": str(item.get("category", "не указана")),
            }
        )
    return result


MISTAKE_PROMPT = """Ты — доброжелательный репетитор для школьника 12–16 лет.

Ученик ошибся в задаче. Объясни коротко (2–3 предложения, на «ты»), в чём именно
ошибка и как решать правильно. Без морализаторства и без «ты невнимателен».
Опирайся на данные ниже. Ответь простым текстом, без markdown и без списков."""


async def explain_mistake(
    question: str,
    correct_answer: str,
    user_answer: str,
    error_label: str,
    explanation: str = "",
) -> str | None:
    """Разбор ошибки словами от ИИ.

    Возвращает None при любой недоступности LLM — у вызывающего всегда остаётся
    правило-базированная рекомендация, поэтому ученик не остаётся без разбора.
    """
    settings = get_settings()
    if not settings.openrouter_api_key:
        return None

    user_content = (
        f"Задача: {question}\n"
        f"Правильный ответ: {correct_answer}\n"
        f"Ответ ученика: {user_answer}\n"
        f"Тип ошибки: {error_label}\n"
        f"Краткое решение: {explanation}"
    )
    body = {
        "model": settings.openrouter_model,
        "temperature": 0.4,
        "max_tokens": 400,
        "messages": [
            {"role": "system", "content": MISTAKE_PROMPT},
            {"role": "user", "content": user_content},
        ],
    }
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/Gemr007/Kompassferum",
        "X-Title": "Kompas",
    }

    try:
        async with httpx.AsyncClient(timeout=settings.openrouter_timeout_seconds) as client:
            response = await client.post(settings.openrouter_url, json=body, headers=headers)
            response.raise_for_status()
            # content бывает null — например, когда модель отказалась отвечать
            # или упёрлась в лимит токенов. Разбор ошибки не обязателен, поэтому
            # это не сбой: у вызывающего остаётся правило-базированный совет.
            content = response.json()["choices"][0]["message"].get("content")
            return content.strip() or None if content else None
    except (httpx.HTTPError, AttributeError, KeyError, IndexError, TypeError, ValueError) as exc:
        logger.warning("Разбор ошибки от ИИ недоступен: %s", exc)
        return None


async def recommend_professions(scores: dict[str, Any]) -> dict[str, Any]:
    """Подобрать 5 профессий по агрегированному профилю ученика.

    Возвращает {"professions": [...], "fallback": bool, "model_used": str,
    "raw_response": {...}}. Исключения наружу не пробрасываются.
    """
    settings = get_settings()

    if not settings.openrouter_api_key:
        logger.warning("OPENROUTER_API_KEY не задан — отдаю rule-based рекомендации")
        result = build_fallback(scores)
        return {**result, "model_used": FALLBACK_MODEL_NAME, "raw_response": {}}

    request_body = {
        "model": settings.openrouter_model,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(scores, ensure_ascii=False)},
        ],
    }
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        # OpenRouter просит идентифицировать приложение
        "HTTP-Referer": "https://github.com/Gemr007/Kompassferum",
        "X-Title": "Kompas",
    }

    raw_response: dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(timeout=settings.openrouter_timeout_seconds) as client:
            response = await client.post(
                settings.openrouter_url, json=request_body, headers=headers
            )
            response.raise_for_status()
            raw_response = response.json()

        content = raw_response["choices"][0]["message"]["content"]
        parsed = json.loads(_strip_markdown_fence(content))
        professions = _validate_professions(parsed)

    except httpx.TimeoutException:
        logger.error("OpenRouter не ответил за %ss", settings.openrouter_timeout_seconds)
    except httpx.HTTPStatusError as exc:
        logger.error(
            "OpenRouter вернул %s: %s", exc.response.status_code, exc.response.text[:500]
        )
    except httpx.HTTPError as exc:
        logger.error("Сетевая ошибка при обращении к OpenRouter: %s", exc)
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
        logger.error("Не удалось разобрать ответ OpenRouter: %s", exc)
    else:
        return {
            "professions": professions,
            "fallback": False,
            "model_used": settings.openrouter_model,
            "raw_response": raw_response,
        }

    result = build_fallback(scores)
    return {**result, "model_used": FALLBACK_MODEL_NAME, "raw_response": raw_response}
