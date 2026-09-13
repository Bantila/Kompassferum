"""Сборка автономной демо-страницы «Компаса» в один HTML-файл.

Результат — demo/kompas-demo.html — лежит в репозитории намеренно: его можно
скачать и открыть в браузере, не устанавливая ни Python, ни Docker.

Берёт настоящие исходники приложения (стили, фронтенд, банк вопросов,
список fallback-профессий) и склеивает их с витриной и демо-двойником
бэкенда. Пересобрать после правок фронтенда:

    python demo/build_demo.py

Снимок сводки по классу берётся из demo/class_summary.json — обновить его
можно так (при поднятом стеке и накатанном app.seed):

    curl "http://localhost/api/teacher/teacher_demo/class-summary?school_class=7Б" \\
        -o demo/class_summary.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services.ai_recommender import FALLBACK_PROFESSIONS, _TYPE_LABELS  # noqa: E402

DEMO = ROOT / "demo"
STATIC = ROOT / "app" / "static"



def _phone_markup(index_html: Path) -> str:
    """Блок <div class="phone">…</div> из index.html целиком."""
    текст = index_html.read_text("utf-8")
    начало = текст.index('<div class="phone">')
    глубина, i = 0, начало
    while i < len(текст):
        if текст.startswith("<div", i):
            глубина += 1
        elif текст.startswith("</div>", i):
            глубина -= 1
            if глубина == 0:
                return текст[начало:i + len("</div>")]
        i += 1
    raise SystemExit("Не удалось выделить разметку приложения из index.html")

def build() -> Path:
    questions = json.loads((ROOT / "app" / "tests_data" / "questions.json").read_text("utf-8"))
    class_summary = json.loads((DEMO / "class_summary.json").read_text("utf-8"))

    app_js = (STATIC / "app.js").read_text("utf-8")
    # единственная правка фронтенда: HTTP-слой заменяется демо-двойником
    # HTTP-слой переехал в shared.js (apiFetch), и подмена перестала находить
    # свою цель — сборка молча ломалась. Ищем текущую форму вызова.
    app_js = app_js.replace(
        "const api = (path, options = {}) => apiFetch(path, options, S.token);",
        """// в автономном демо запросы обслуживает DEMO.handle, а не сеть
const api = (path, options = {}) => DEMO.handle(path, options);""",
    )
    app_js = app_js.replace(
        """    teacher: () => { window.location.href = '/static/teacher.html'; },""",
        """    teacher: () => document.querySelector('[data-tab="teacher"]').click(),""",
    )
    if "DEMO.handle" not in app_js:
        raise SystemExit("Не удалось подменить api() — проверьте app/static/app.js")

    data = {
        "questions": questions,
        "classSummary": class_summary,
        "fallbackProfessions": FALLBACK_PROFESSIONS,
        "typeLabels": _TYPE_LABELS,
    }

    html = (DEMO / "shell.html").read_text("utf-8")
    # Разметку приложения берём из настоящего index.html, а не держим копию в
    # шаблоне: копия уже разошлась — в неё не доехали вкладки, tabsBar оказался
    # null, и демо не отрисовывалось вовсе.
    html = html.replace("{{PHONE}}", _phone_markup(STATIC / "index.html"))
    html = html.replace("{{STYLES}}", (STATIC / "styles.css").read_text("utf-8"))
    html = html.replace("{{DATA}}", json.dumps(data, ensure_ascii=False))
    html = html.replace("{{DEMO_JS}}", (DEMO / "demo.js").read_text("utf-8"))
    html = html.replace("{{APP_JS}}", app_js)

    out = DEMO / "kompas-demo.html"
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    path = build()
    print(f"{path.relative_to(ROOT)} — {path.stat().st_size / 1024:.0f} КБ")
