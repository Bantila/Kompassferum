# Компас — ИИ-навигатор по профессиям

Прототип для хакатона «Идея фикс», трек «Искусственный интеллект в школьных процессах».

Ученик 12–16 лет проходит психометрический тест из 74 вопросов прямо в чат-боте
MAX/Сферум. Нейросеть по результатам подбирает 5 профессий с обоснованием, опирающимся
на конкретные баллы, и говорит, какие предметы стоит подтянуть. Педагог видит
агрегированную сводку по классу — без имён и персональных данных.

Ключевое отличие от типовых профориентационных тестов: **способности проверяются
задачами с правильным ответом, а не самооценкой**. Самооценка школьника о своих
способностях ненадёжна — на неё влияют тревожность, оценки учителя и склонность
себя переоценивать или недооценивать. Самооценкой остаётся только интерес: интерес
по определению нельзя проверить задачей.

## Стек

| Слой | Технология |
|---|---|
| API | Python 3.12, FastAPI, Pydantic v2 |
| БД | PostgreSQL 16, SQLAlchemy 2.0 (async), Alembic |
| ИИ | OpenRouter, модель `moonshotai/kimi-k2` |
| HTTP | httpx (async) |
| Инфраструктура | Docker (multistage), docker compose, nginx |

Наружу торчит только nginx. uvicorn и PostgreSQL живут внутри docker-сети и портов
не пробрасывают.

## Требования

- Docker 24+
- Docker Compose v2 (`docker compose`, не `docker-compose`)
- Ключ OpenRouter — https://openrouter.ai/keys (без него сервис работает, но
  отдаёт рекомендации упрощённым алгоритмом)

## Запуск

```bash
git clone https://github.com/Gemr007/Kompassferum.git
cd Kompassferum

cp .env.example .env
# открыть .env и заполнить: OPENROUTER_API_KEY, POSTGRES_PASSWORD, MAX_WEBHOOK_SECRET

docker compose up -d --build

# накатить миграции
docker compose exec backend alembic upgrade head

# проверить, что стек живой
curl http://localhost/health
# {"status":"ok","database":"ok"}
```

Swagger-документация: http://localhost/docs

Остановить: `docker compose down`. Вместе с данными: `docker compose down -v`.

## Переменные окружения

| Переменная | Назначение |
|---|---|
| `DATABASE_URL` | Строка подключения backend → postgres |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Учётка контейнера БД, должна совпадать с `DATABASE_URL` |
| `OPENROUTER_API_KEY` | Ключ OpenRouter. Пустой → всегда rule-based рекомендации |
| `OPENROUTER_MODEL` | Slug модели, по умолчанию `moonshotai/kimi-k2` |
| `MAX_WEBHOOK_SECRET` | Секрет для проверки заголовка `X-Max-Signature` на вебхуке |

Секреты читаются только из окружения, в коде их нет.

## API

### Получить вопросы

Правильные ответы (`correct_index`) никогда не уезжают вместе с вопросом — иначе
ученик увидел бы их в теле ответа API до того, как выберет вариант.

```bash
# весь тест
curl http://localhost/api/tests/questions

# только блок B и только точные науки — короткая сессия на один заход
curl "http://localhost/api/tests/questions?block=b&subject_group=exact"
```

Группы предметов: `exact`, `natural`, `humanities`, `creative`.

### Проверить один ответ

```bash
curl -X POST http://localhost/api/tests/check-answer \
  -H 'Content-Type: application/json' \
  -d '{"question_id": "b1_k1", "selected_index": 1, "time_spent_seconds": 12}'
# {"question_id":"b1_k1","is_correct":true,"correct_index":1}
```

### Отправить результаты теста

```bash
curl -X POST http://localhost/api/tests/submit \
  -H 'Content-Type: application/json' \
  -d '{
    "max_user_id": "max_user_123",
    "school_class": "7Б",
    "answers": {
      "a1": 5, "a2": 4, "a3": 5, "a4": 5,
      "b1_k1": 1, "b1_k2": 0, "b1_k3": 0, "b1_interest": 5,
      "b10_k1": {"selected_index": 1, "time_spent_seconds": 8},
      "c1": 4, "c2": 3, "c7": 5, "c8": 5
    }
  }'
```

Отвечать можно частями: тест из 74 вопросов проходится за несколько сессий,
`progress` в ответе показывает, сколько уже пройдено.

### Остальное

```bash
# сохранённые рекомендации по id результата
curl http://localhost/api/recommendations/<test_result_id>

# история прохождений — видно, как меняются интересы со временем
curl http://localhost/api/users/max_user_123/history

# сводка по классу (только для пользователя с ролью teacher)
curl "http://localhost/api/teacher/<teacher_max_id>/class-summary?school_class=7Б"

# вебхук MAX
curl -X POST http://localhost/api/webhook/max \
  -H 'X-Max-Signature: <MAX_WEBHOOK_SECRET>' \
  -H 'Content-Type: application/json' \
  -d '{"update_type": "message_created"}'
```

## Как считаются баллы

**Блок A — интересы** (12 вопросов). Типология Голланда: 6 типов × 2 вопроса,
шкала 1–5. Пара усредняется.

**Блок B — предметы** (52 вопроса). 13 предметов × (3 задачи с правильным ответом
разной сложности + 1 вопрос про интерес).

```
knowledge_score = 1 + 4 * (правильных / всего)   # 0/3 → 1.0, 1/3 → 2.3, 2/3 → 3.7, 3/3 → 5.0
subject_score   = knowledge_score * 0.65 + interest * 0.35
```

Знание весит больше, потому что это единственный объективный сигнал в блоке;
интерес учитывается как модификатор мотивации.

**Блок C — soft skills** (10 вопросов). 5 черт × 2 формулировки, пара усредняется:
teamwork, leadership, creativity, analytical, resilience.

## Рекомендации и запасной вариант

`services/ai_recommender.py` зовёт OpenRouter с `temperature=0.3` и таймаутом 30 с,
снимает markdown-обёртку с ответа и валидирует структуру.

Любой сбой — таймаут, не-200, невалидный JSON, отсутствие ключа — не приводит к 500-й
ошибке. Вместо этого включается rule-based подбор по самому выраженному типу Голланда,
и в ответе выставляется `"fallback": true`, чтобы бот показал ученику честное
«рекомендации сформированы упрощённым алгоритмом». Демо не падает из-за чужого API.

## Структура

```
├── app/
│   ├── main.py                     # FastAPI, CORS, /health
│   ├── config.py                   # pydantic-settings, чтение .env
│   ├── database.py                 # async engine, session, Base
│   ├── models/                     # User, TestResult, Recommendation
│   ├── schemas/                    # Pydantic-схемы запросов и ответов
│   ├── routers/                    # tests, recommendations, teacher, webhook
│   ├── services/
│   │   ├── test_scoring.py         # банк вопросов и calculate_scores
│   │   └── ai_recommender.py       # OpenRouter + rule-based fallback
│   └── tests_data/questions.json   # 74 вопроса
├── tests/                          # pytest, БД — SQLite in-memory
├── alembic/                        # миграции
├── nginx/nginx.conf                # reverse proxy, единственная точка входа
├── Dockerfile                      # multistage: builder → runtime
└── docker-compose.yml              # nginx + backend + postgres
```

## Тесты

```bash
docker compose exec backend pytest -q
```

Или локально, без Docker:

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest -q
```

Тесты используют SQLite (`aiosqlite`) и мок httpx — поднятый PostgreSQL и реальные
запросы к OpenRouter им не нужны. PostgreSQL остаётся основной БД проекта, SQLite
живёт только в фикстурах.

## Известные ограничения MVP

- **Нет авторизации.** `max_user_id` приходит из тела запроса и никак не
  подтверждается. В бою нужен OAuth MAX и проверка, что запрос пришёл от
  заявленного пользователя.
- **Вебхук MAX — заглушка.** Проверка секрета, логирование и 200 OK работают
  по-настоящему, разбор payload — нет: формат событий уточняется после получения
  документации платформы. Подпись сейчас — прямое сравнение секрета из заголовка;
  если MAX подписывает тело HMAC-ом, логику нужно будет заменить.
- **Роль педагога никем не подтверждается.** Сводка по классу отдаётся любому
  пользователю с `role=teacher`; связь «педагог ↔ его класс» не проверяется.
- **Согласия на обработку данных не хранятся.** Сводка ограничена k-анонимностью
  (не формируется, пока тест не прошли хотя бы 3 ученика), но реестра согласий нет.
- **Банк вопросов небольшой** — 3 задачи на предмет. Для устойчивой оценки нужен
  пул побольше с ротацией, иначе ответы быстро разойдутся между учениками.
- **Антифрод не реализован.** Время ответа сохраняется в `raw_answers`, но в
  скоринге не участвует — это задел на будущее.
- **CORS открыт для всех origin** до тех пор, пока не известен домен мини-приложения MAX.
- **Миграции накатываются вручную** после `docker compose up`, автоматического
  прогона на старте контейнера нет.
