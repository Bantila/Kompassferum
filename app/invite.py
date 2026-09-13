"""Выписать код приглашения педагога из консоли сервера.

    docker compose exec backend python -m app.invite
    docker compose exec backend python -m app.invite "Иванова, 7Б"

Нужен для первого педагога: пригласить его некому, а открывать ради этого
регистрацию для всех — ровно та дыра, которую код и закрывает. Дальше педагоги
приглашают коллег сами через POST /api/auth/invites.

Доступ к консоли сервера здесь и есть подтверждение полномочий.
"""

from __future__ import annotations

import asyncio
import sys

from app.database import SessionLocal
from app.services import invites


async def main() -> None:
    подпись = " ".join(sys.argv[1:]).strip()

    async with SessionLocal() as session:
        invite = await invites.create(session, note=подпись)
        await session.commit()
        код, истекает = invite.code, invite.expires_at

    print()
    print(f"  Код приглашения: {код}")
    if подпись:
        print(f"  Для кого:        {подпись}")
    print(f"  Действует до:    {истекает:%d.%m.%Y %H:%M} UTC")
    print()
    print("  Код одноразовый. Передайте его педагогу — он введёт его при регистрации.")
    print()


if __name__ == "__main__":
    asyncio.run(main())
