"""Схемы согласия на обработку персональных данных."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ConsentGrantRequest(BaseModel):
    # до 14 лет согласие даёт законный представитель — в реестре это видно
    granted_by: Literal["self", "parent"] = "self"


class ConsentStatusOut(BaseModel):
    granted: bool
    # редакция, действующая сейчас: с ней сверяется то, на что согласились
    current_version: str
    document_version: str | None = None
    granted_by: str | None = None
    granted_at: datetime | None = None
    # текст согласия сменился после того, как человек его принял
    outdated: bool = False


class ConsentRecordOut(BaseModel):
    """Одна запись журнала: когда согласие дано и когда закрыто."""

    document_version: str
    granted_by: str
    granted_at: datetime
    revoked_at: datetime | None = None


class ConsentJournalOut(BaseModel):
    # свежие записи сверху; действующая — та, у которой нет revoked_at
    records: list[ConsentRecordOut]


class ConsentRevokedOut(BaseModel):
    revoked: bool
    deleted_records: int = Field(description="Сколько записей удалено при отзыве")
