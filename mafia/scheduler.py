from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select

from mafia.config import Settings
from mafia.db import repo
from mafia.db.session import session_scope
from mafia.runner import Runner

log = logging.getLogger("scheduler")


async def run_scheduler(runner: Runner, settings: Settings) -> None:
    last_lobby_check = 0.0
    while True:
        now = int(time.time())
        try:
            await runner.tick(now)
            if now - last_lobby_check >= 60:
                last_lobby_check = now
                await _expire_lobbies(settings, runner.bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(1)


async def _expire_lobbies(settings: Settings, bot: Bot) -> None:
    from mafia.db.models import Lobby

    now = datetime.now(UTC)
    async with session_scope() as session:
        rows = list((await session.execute(select(Lobby))).scalars())
        expired = []
        for r in rows:
            if r.created_at is None:
                continue
            created = r.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            if (now - created).total_seconds() > settings.lobby_timeout_s:
                expired.append(r)
        for r in expired:
            await repo.delete_lobby(session, r.chat_id)
    for r in expired:
        if r.msg_id:
            try:
                await bot.edit_message_text(
                    "⌛ Лобби закрыто по таймауту.",
                    chat_id=r.chat_id,
                    message_id=r.msg_id,
                )
            except TelegramAPIError:
                pass
    if expired:
        log.info("expired %d lobbies", len(expired))
