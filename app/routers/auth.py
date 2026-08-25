"""Регистрация, вход и профиль.

У ученика ровно один путь входа — подпись мессенджера (/miniapp). Ни почты,
ни гостевого режима у него нет: раньше один человек мог завести аккаунт на
сайте и второй через Telegram, и это были разные записи с разным прогрессом.

Регистрация и вход по почте остались только для педагогов: кабинет с
классами открывается в обычном браузере, где подписи мессенджера нет.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.services.rate_limit import limit
from app.models import BotAccount, User, UserRole
from app.schemas.auth import (
    InviteCreateRequest,
    InviteOut,
    LoginRequest,
    MiniAppLoginRequest,
    ProfileOut,
    RegisterRequest,
    TokenResponse,
)
from app.services import invites
from app.services.miniapp_auth import full_name_from, verify_max, verify_telegram
from app.services.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _profile(user: User) -> ProfileOut:
    return ProfileOut(
        id=user.id,
        max_user_id=user.max_user_id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        grade=user.grade,
        class_id=user.class_id,
        school_class=user.school_class,
    )


async def get_current_user(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Пользователь из заголовка Authorization: Bearer <token>."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Нужен вход в аккаунт")

    user_id = decode_access_token(authorization.split(" ", 1)[1].strip())
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Токен недействителен — войдите заново")

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Аккаунт не найден или отключён")
    return user


async def get_current_user_optional(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User | None:
    """Пользователь, если он вошёл, иначе None.

    Для эндпоинтов, которые обязаны работать и анонимно: демо-страница и первый
    заход в мини-приложение идут без токена, и падать там нельзя.
    """
    if not authorization:
        return None
    try:
        return await get_current_user(authorization=authorization, session=session)
    except HTTPException:
        return None


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    # регистрация педагогов штучная: пять аккаунтов в час с адреса — с запасом
    dependencies=[Depends(limit("register", times=5, seconds=3600))],
)
async def register(
    payload: RegisterRequest, session: AsyncSession = Depends(get_session)
) -> TokenResponse:
    """Регистрация педагога. Ученику этот путь закрыт — он входит через мессенджер."""
    email = payload.email.strip().lower()
    taken = await session.scalar(select(User).where(func.lower(User.email) == email))
    if taken is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Аккаунт с такой почтой уже есть — войдите")

    user = User(
        max_user_id=f"web_{secrets.token_hex(6)}",
        email=email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name.strip(),
        # роль жёстко задана здесь, а не приходит из запроса: иначе через эту
        # ручку снова можно было бы завести ученика в обход мессенджера
        role=UserRole.teacher,
        is_active=True,
    )
    session.add(user)
    await session.flush()

    # Код гасим уже за созданным пользователем. Не подошёл — исключение
    # откатывает транзакцию целиком, недорегистрированный аккаунт не остаётся.
    if not await invites.redeem(session, payload.invite_code, user.id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Код приглашения недействителен, истёк или уже использован",
        )

    await session.commit()
    await session.refresh(user)
    logger.info("Регистрация педагога: %s", email)
    return TokenResponse(access_token=create_access_token(user.id), user=_profile(user))


@router.post("/invites", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
async def create_invite(
    payload: InviteCreateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> InviteOut:
    """Выписать код приглашения коллеге.

    Приглашать может только тот, кто сам уже подтверждён: иначе цепочка доверия
    рвётся на первом же звене и код перестаёт что-либо значить.
    """
    if user.role is not UserRole.teacher:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Приглашать коллег может только педагог")

    invite = await invites.create(session, created_by=user, note=payload.note)
    await session.commit()
    logger.info("Код приглашения выписан педагогом %s", user.email)
    return InviteOut(
        code=invite.code, note=invite.note, expires_at=invite.expires_at, used_at=None
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    # десять попыток в минуту: человек с забытым паролем уложится, перебор — нет
    dependencies=[Depends(limit("login", times=10, seconds=60))],
)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_session)) -> TokenResponse:
    email = payload.email.strip().lower()
    user = await session.scalar(select(User).where(func.lower(User.email) == email))

    # одинаковый ответ на «нет такого email» и «неверный пароль» —
    # иначе форма входа превращается в проверялку существующих аккаунтов
    if user is None or not user.hashed_password or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверная почта или пароль")
    if not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Аккаунт отключён")

    return TokenResponse(access_token=create_access_token(user.id), user=_profile(user))


@router.post(
    "/miniapp",
    response_model=TokenResponse,
    # Класс сидит за одним NAT и открывает приложение одновременно — лимит
    # должен вмещать весь кабинет разом, иначе половина урока не войдёт.
    dependencies=[Depends(limit("miniapp", times=60, seconds=60))],
)
async def miniapp_login(
    payload: MiniAppLoginRequest, session: AsyncSession = Depends(get_session)
) -> TokenResponse:
    """Вход из мини-приложения мессенджера.

    Подпись initData доказывает, кто открыл приложение, поэтому регистрация
    не нужна: аккаунт заводится сам при первом открытии. Если этот же человек
    уже писал боту, используется его существующая учётная запись — прогресс из
    чата и из приложения общий.
    """
    verify = verify_telegram if payload.platform == "telegram" else verify_max
    profile = verify(payload.init_data)
    if profile is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Не удалось подтвердить, что запрос пришёл из мессенджера"
        )

    account = await session.scalar(
        select(BotAccount).where(
            BotAccount.platform == profile["platform"],
            BotAccount.external_id == profile["external_id"],
        )
    )

    user = await session.get(User, account.user_id) if account and account.user_id else None
    if user is None:
        user = User(
            max_user_id=f"{profile['platform']}_{profile['external_id']}",
            role=UserRole.student,
            full_name=full_name_from(profile),
        )
        session.add(user)
        await session.flush()
        logger.info("Мини-приложение: заведён аккаунт для %s", user.max_user_id)

    # связываем чат и аккаунт, чтобы бот сразу знал, чей это прогресс
    if account is None:
        account = BotAccount(
            platform=profile["platform"],
            external_id=profile["external_id"],
            chat_id=profile["external_id"],
            user_id=user.id,
        )
        session.add(account)
    else:
        account.user_id = user.id
        account.link_code = None

    await session.commit()
    await session.refresh(user)
    return TokenResponse(access_token=create_access_token(user.id), user=_profile(user))


@router.get("/me", response_model=ProfileOut)
async def me(user: User = Depends(get_current_user)) -> ProfileOut:
    return _profile(user)
