"""Схемы привязки чат-бота к аккаунту."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LinkBotRequest(BaseModel):
    code: str = Field(min_length=4, max_length=8)


class LinkBotResponse(BaseModel):
    platform: str
    linked: bool
