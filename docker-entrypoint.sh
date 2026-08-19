#!/bin/sh
# Миграции накатываются при старте контейнера: на демо один шаг «docker compose up»
# надёжнее, чем инструкция «не забудьте выполнить alembic upgrade head».
set -e

echo "Ждём PostgreSQL…"
python - <<'PY'
import asyncio, os, sys
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def wait():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    for attempt in range(30):
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            await engine.dispose()
            return
        except Exception as exc:
            print(f"  попытка {attempt + 1}/30: {exc.__class__.__name__}")
            await asyncio.sleep(2)
    sys.exit("PostgreSQL не поднялся за 60 секунд")

asyncio.run(wait())
PY

echo "Накатываем миграции…"
alembic upgrade head

exec "$@"
