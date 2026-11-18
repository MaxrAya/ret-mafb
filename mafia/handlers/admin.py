from __future__ import annotations

import asyncio
import time

from aiogram import Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import func, select

from mafia.config import get_settings
from mafia.db import repo
from mafia.db.models import Achievement, ChatStats, Match, PlayerStats, Tournament, User
from mafia.db.session import session_scope
from mafia.game import engine
from mafia.game.engine import EngineError
from mafia.runner import Runner
from mafia.ui import texts as T

router = Router(name="admin")

GIF_KINDS = {"start", "night", "day", "vote", "end"}

WINNER_ALIASES = {
    "town": T.WINNER_TOWN,
    "город": T.WINNER_TOWN,
    "mafia": T.WINNER_MAFIA,
    "мафия": T.WINNER_MAFIA,
}


async def _chat_admin(msg: Message) -> bool:
    if msg.from_user is None:
        return False
    if msg.from_user.id in get_settings().admins:
        return True
    try:
        member = await msg.bot.get_chat_member(msg.chat.id, msg.from_user.id)
    except TelegramAPIError:
        return False
    return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)


@router.message(Command("setgif"))
async def cmd_setgif(msg: Message, runner: Runner) -> None:
    if msg.chat.type not in ("group", "supergroup"):
        await msg.answer("Команда работает в группе.")
        return
    if not await _chat_admin(msg):
        await msg.answer("Только администратор чата может ставить гифки.")
        return
    parts = (msg.text or "").split()
    if len(parts) < 2 or parts[1].lower() not in GIF_KINDS:
        await msg.answer(
            "Использование: ответьте командой на гифку в чате:\n"
            "/setgif night|day|vote|end|start"
        )
        return
    kind = parts[1].lower()
    reply = msg.reply_to_message
    file_id: str | None = None
    if reply is not None and reply.animation is not None:
        file_id = reply.animation.file_id
    elif reply is not None and reply.video is not None:
        file_id = reply.video.file_id
    if file_id is None:
        await msg.answer("Ответьте командой на гифку (или видео).")
        return
    async with session_scope() as session:
        await repo.set_gif(session, msg.chat.id, kind, file_id)
    runner.gif_put(msg.chat.id, kind, file_id)
    await msg.answer(
        f"🎬 Гифка «{kind}» сохранена — теперь на этой фазе бот показывает её."
    )


@router.message(Command("admin_stop"))
async def cmd_stop(msg: Message, runner: Runner) -> None:
    if msg.chat.type not in ("group", "supergroup"):
        return
    if not await _chat_admin(msg):
        await msg.answer("Только администратор чата.")
        return
    async with session_scope() as session:
        mid = await repo.active_match_in_chat(session, msg.chat.id)
    if mid is None:
        await msg.answer("Активной партии нет.")
        return
    await runner.abort_chat(msg.chat.id, "Остановлено администратором.")
    await msg.answer("🛑 Партия остановлена без подсчёта рейтинга.")


@router.message(Command("admin_reset"))
async def cmd_reset(msg: Message) -> None:
    if msg.from_user is None or msg.from_user.id not in get_settings().admins:
        await msg.answer("Команда только для владельца бота.")
        return
    uid: int | None = None
    if msg.reply_to_message and msg.reply_to_message.from_user:
        uid = msg.reply_to_message.from_user.id
    else:
        parts = (msg.text or "").split()
        if len(parts) > 1 and parts[1].lstrip("@").isdigit():
            uid = int(parts[1].lstrip("@"))
    if uid is None:
        await msg.answer("Ответьте на сообщение игрока или укажите его ID: /admin_reset 123")
        return
    async with session_scope() as session:
        st = await session.get(PlayerStats, uid)
        if st is not None:
            await session.delete(st)
        rows = (
            await session.execute(select(ChatStats).where(ChatStats.user_id == uid))
        ).scalars()
        for cs in list(rows):
            await session.delete(cs)
        ach_rows = (
            await session.execute(select(Achievement).where(Achievement.user_id == uid))
        ).scalars()
        for a in list(ach_rows):
            await session.delete(a)
    await msg.answer(f"♻️ Статистика игрока {uid} сброшена.")


@router.message(Command("admin_broadcast"))
async def cmd_broadcast(msg: Message, command: CommandObject) -> None:
    if msg.from_user is None or msg.from_user.id not in get_settings().admins:
        await msg.answer("Команда только для владельца бота.")
        return
    text = (command.args or "").strip()
    if not text:
        await msg.answer("Использование: /admin_broadcast текст рассылки")
        return
    async with session_scope() as session:
        ids = list((await session.execute(select(User.id))).scalars())
    sent = 0
    failed = 0
    for uid in ids:
        try:
            await msg.bot.send_message(uid, text, parse_mode="HTML")
            sent += 1
        except (TelegramForbiddenError, TelegramAPIError):
            failed += 1
        await asyncio.sleep(0.05)
    await msg.answer(
        f"📤 Рассылка готова: доставлено {sent}, недоступно {failed}."
    )


@router.message(Command("forcend"))
async def cmd_forcend(msg: Message, command: CommandObject, runner: Runner) -> None:
    if msg.chat.type not in ("group", "supergroup"):
        await msg.answer("Команда работает в группе.")
        return
    if not await _chat_admin(msg):
        await msg.answer("Только администратор чата.")
        return
    async with session_scope() as session:
        mid = await repo.active_match_in_chat(session, msg.chat.id)
    if mid is None:
        await msg.answer("Активной партии нет.")
        return

    arg = (command.args or "").strip().lower()
    if arg:
        winner = WINNER_ALIASES.get(arg)
        if winner is None:
            await msg.answer(
                "Победитель: town (город) или mafia (мафия).\n"
                "Пример: /forcend town"
            )
            return
    else:
        async with session_scope() as session:
            state = await repo.load_state(session, mid)
        if state is None:
            await msg.answer("Активной партии нет.")
            return
        winner = engine.current_winner(state)
        if winner is None:
            await msg.answer(
                "Победитель не определился (равные силы). Укажите явно:\n"
                "/forcend town или /forcend mafia"
            )
            return

    await runner.force_end(mid, winner)
    await msg.answer(
        f"🏁 Партия завершена принудительно — {T.WINNER_TITLE[winner]}, "
        "рейтинг посчитан."
    )


@router.message(Command("admin_skip"))
async def cmd_admin_skip(msg: Message, runner: Runner) -> None:
    if msg.chat.type not in ("group", "supergroup"):
        await msg.answer("Команда работает в группе.")
        return
    if not await _chat_admin(msg):
        await msg.answer("Только администратор чата.")
        return
    async with session_scope() as session:
        mid = await repo.active_match_in_chat(session, msg.chat.id)
    if mid is None:
        await msg.answer("Активной партии нет.")
        return
    now = int(time.time())
    try:
        await runner.run(mid, lambda s: engine.host_skip(s, now))
    except EngineError as e:
        await msg.answer(str(e))
        return
    await msg.answer("⏭ Фаза пропущена администратором.")


@router.message(Command("admin_stats"))
async def cmd_admin_stats(msg: Message) -> None:
    if msg.from_user is None or msg.from_user.id not in get_settings().admins:
        await msg.answer("Команда только для владельца бота.")
        return
    async with session_scope() as session:
        users = (await session.execute(select(func.count(User.id)))).scalar() or 0
        matches = (await session.execute(select(func.count(Match.id)))).scalar() or 0
        active = (
            await session.execute(
                select(func.count(Match.id)).where(Match.status == "active")
            )
        ).scalar() or 0
        finished = (
            await session.execute(
                select(func.count(Match.id)).where(Match.status == "finished")
            )
        ).scalar() or 0
        tours = (await session.execute(select(func.count(Tournament.id)))).scalar() or 0
    await msg.answer(
        "📈 <b>Статистика бота</b>\n"
        f"Игроков: {users}\n"
        f"Партий: {matches} (активных: {active}, завершено: {finished})\n"
        f"Турниров: {tours}",
        parse_mode="HTML",
    )
