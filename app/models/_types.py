"""Общие типы колонок.

JSONB — на PostgreSQL (основная БД), обычный JSON — на SQLite в pytest.
"""

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

JSONColumn = JSON().with_variant(JSONB(), "postgresql")
