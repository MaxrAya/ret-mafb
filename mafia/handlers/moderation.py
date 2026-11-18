from __future__ import annotations

import logging
import time

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from mafia.config import get_settings
from mafia.db import repo
from mafia.db.session import session_scope
from mafia.game.engine import Phase

router = Router(name="moderation")

log = logging.getLogger("moderation")

MEDIA_TYPES = {
    "photo",
    "video",
    "document",
    "animation",
    "sticker",
    "video_note",
    "voice",
    "audio",
}

BAD_STEMS = (
    "хуй", "хуя", "хуе", "хую", "пизд", "бляд", "блят", "заеб",
    "ебан", "ебл", "выеб", "мудак", "мудац", "говн",
    "дерьм", "шлюх", "сука", "суки", "сукой", "сучк", "пидор", "пидар",
    "дроч", "сосат", "жоп", "нахуй", "похуй",
)


def has_profanity(text: str) -> bool:
    t = text.lower().replace("ё", "е")
    return any(stem in t for stem in BAD_STEMS)

_cool: dict[tuple[int, str], float] = {}


def _allow(chat_id: int, kind: str, cooldown: int) -> bool:
    key = (chat_id, kind)
    now = time.time()
    if _cool.get(key, 0) + cooldown > now:
        return False
    _cool[key] = now
    return True


async def _warn(msg: Message, text: str) -> None:
    try:
        await msg.answer(text)
    except TelegramAPIError:
        log.debug("warn failed", exc_info=True)


async def _drop(msg: Message) -> None:
    try:
        await msg.delete()
    except TelegramAPIError:
        log.debug("delete failed", exc_info=True)


@router.message(F.chat.type.in_(["group", "supergroup"]))
async def moderate(msg: Message) -> None:
    if msg.from_user is None or msg.from_user.is_bot:
        return
    text = msg.text or ""
    is_cmd = text.startswith("/")
    is_media = msg.content_type in MEDIA_TYPES
    settings = get_settings()

    if is_cmd:
        return

    if text and has_profanity(text):
        await _drop(msg)
        if _allow(msg.chat.id, "prof", settings.media_warn_cooldown_s):
            await _warn(msg, "🚫 Мат и оскорбления здесь запрещены.")
        return

    async with session_scope() as session:
        mid = await repo.active_match_in_chat(session, msg.chat.id)
        if mid is None:
            return
        state = await repo.load_state(session, mid)
    if state is None or state.phase == Phase.ENDED:
        return

    if is_media:
        await _drop(msg)
        if _allow(msg.chat.id, "media", settings.media_warn_cooldown_s):
            await _warn(msg, "🚫 Медиа, фото и скриншоты во время партии запрещены.")
        return

    if state.phase == Phase.NIGHT:
        await _drop(msg)
        if _allow(msg.chat.id, "night", settings.media_warn_cooldown_s):
            await _warn(msg, "🌙 Ночь — в чате тишина.")
        return

    player = state.by_user(msg.from_user.id)
    if player is not None and not player.alive:
        await _drop(msg)
        if _allow(msg.chat.id, "dead", settings.dead_warn_cooldown_s):
            await _warn(msg, "💀 Мёртвые молчат до конца партии.")
