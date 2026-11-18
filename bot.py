from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeDefault,
    TelegramObject,
)

from mafia.config import get_settings
from mafia.db import repo
from mafia.db.session import create_schema, dispose_db, init_db, session_scope
from mafia.handlers import register_all
from mafia.runner import Runner
from mafia.scheduler import run_scheduler

log = logging.getLogger("bot")


class UserCapture(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = getattr(event, "from_user", None)
        if user is not None and not user.is_bot:
            try:
                async with session_scope() as session:
                    await repo.ensure_user(
                        session, user.id, user.full_name, user.username
                    )
            except Exception:
                log.debug("ensure_user failed", exc_info=True)
        return await handler(event, data)


async def main() -> None:
    try:
        settings = get_settings()
    except Exception:
        print(
            "BOT_TOKEN не задан. Скопируй .env.example в .env и впиши токен от @BotFather."
        )
        sys.exit(1)
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    init_db(settings.db_path)
    await create_schema()

    bot = Bot(
        settings.bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = Dispatcher()
    runner = Runner(bot)
    dp["runner"] = runner
    dp.update.middleware(UserCapture())
    register_all(dp)

    try:
        me = await bot.get_me()
    except Exception:
        log.error("Неверный токен или нет сети. Проверь BOT_TOKEN в .env")
        await bot.session.close()
        await dispose_db()
        sys.exit(1)
    log.info("Bot started as @%s", me.username)

    commands = [
        BotCommand(command="start", description="начать и справка"),
        BotCommand(command="mafia", description="создать лобби"),
        BotCommand(command="game", description="состояние партии"),
        BotCommand(command="skip", description="пропустить фазу (хост)"),
        BotCommand(command="profile", description="ваша статистика"),
        BotCommand(command="top", description="рейтинг"),
        BotCommand(command="achievements", description="достижения"),
        BotCommand(command="matches", description="последние партии"),
        BotCommand(command="tournament", description="турниры"),
        BotCommand(command="help", description="все команды"),
        BotCommand(command="rules", description="правила игры"),
        BotCommand(command="subscribe", description="уведомления о сборах в ЛС"),
        BotCommand(command="unsubscribe", description="выключить уведомления"),
        BotCommand(command="setgif", description="гифка фазы (админ)"),
        BotCommand(command="forcend", description="завершить партию (админ)"),
    ]
    for scope in (BotCommandScopeDefault(), BotCommandScopeAllGroupChats()):
        await bot.set_my_commands(commands, scope=scope)
    stored = await bot.get_my_commands()
    log.info("Commands registered: %d", len(stored))

    scheduler_task = asyncio.create_task(run_scheduler(runner, settings))
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
        await bot.session.close()
        await dispose_db()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
