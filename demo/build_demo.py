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


def build() -> Path:
    questions = json.loads((ROOT / "app" / "tests_data" / "questions.json").read_text("utf-8"))
    class_summary = json.loads((DEMO / "class_summary.json").read_text("utf-8"))

    app_js = (STATIC / "app.js").read_text("utf-8")
    # единственная правка фронтенда: HTTP-слой заменяется демо-двойником
    app_js = app_js.replace(
        """async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status}: ${body.slice(0, 300)}`);
  }
  return response.json();
}""",
        """async function api(path, options = {}) {
  // в автономном демо запросы обслуживает DEMO.handle, а не сеть
  return DEMO.handle(path, options);
}""",
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
