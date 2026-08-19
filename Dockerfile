# ---------- Stage 1: builder ----------
FROM python:3.12-slim AS builder

WORKDIR /app

# Системные зависимости, нужные ТОЛЬКО для сборки некоторых пакетов
# (например, asyncpg/psycopg могут требовать компиляции)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Собираем зависимости в виртуальное окружение — так его целиком
# можно скопировать во второй stage, не таща build-essential с собой
COPY requirements.txt .
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir -r requirements.txt


# ---------- Stage 2: runtime ----------
FROM python:3.12-slim AS runtime

# Только рантайм-зависимость для psycopg/asyncpg (без -dev, без build-essential)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Забираем готовое окружение с зависимостями из первого stage —
# компиляторы и dev-заголовки в финальный образ не попадают
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Непривилегированный пользователь — не запускаем приложение от root
RUN useradd --create-home --shell /bin/bash appuser

COPY --chown=appuser:appuser . .

# Подстраховка на случай сборки из рабочей копии с CRLF (Windows):
# без этого shebang ломается и контейнер не стартует
RUN sed -i 's/$//' /app/docker-entrypoint.sh && chmod +x /app/docker-entrypoint.sh

USER appuser

EXPOSE 8000

# Healthcheck самого контейнера — использует curl, установленный выше
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Миграции накатываются в entrypoint, дальше запускается uvicorn
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
