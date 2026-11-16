from __future__ import annotations

import html

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from mafia.db import repo
from mafia.db.session import session_scope
from mafia.game.roles import GameSettings
from mafia.runner import Runner
from mafia.ui import keyboards as kb

router = Router(name="tournament")

HELP = (
    "🏆 <b>Турнир</b> — серия партий в чате с общей таблицей.\n\n"
    "/tournament create [раундов] [очков] — создать (по умолчанию 5 и 3)\n"
    "/tournament join — войти\n"
    "/tournament leave — выйти\n"
    "/tournament start — начать (хост)\n"
    "/tournament top — таблица\n"
    "/tournament cancel — отменить (хост)"
)


def esc(t: str | None) -> str:
    return html.escape(t or "")


async def _table(t_id: int) -> str:
    async with session_scope() as session:
        players = await repo.tournament_players(session, t_id)
    if not players:
        return "Пока никто не записался."
    lines = [
        f"{i}. {esc(p.name)} — {p.points} очк. ({p.wins} побед)"
        for i, p in enumerate(players, 1)
    ]
    return "\n".join(lines)


async def _refresh(msg_or_cb, t_id: int, msg_id: int | None, can_start: bool) -> None:
    if not msg_id:
        return
    table = await _table(t_id)
    text = f"🏆 <b>Турнир</b>\n\n{table}"
    try:
        await msg_or_cb.bot.edit_message_text(
            text,
            chat_id=msg_or_cb.chat.id if hasattr(msg_or_cb, "chat") else msg_or_cb.message.chat.id,
            message_id=msg_id,
            parse_mode="HTML",
            reply_markup=kb.tournament_kb(can_start),
        )
    except TelegramBadRequest:
        pass


@router.message(Command("tournament"))
async def cmd_tournament(msg: Message, runner: Runner) -> None:
    _ = runner
    if msg.chat.type not in ("group", "supergroup"):
        await msg.answer("Команда работает в группе.")
        return
    assert msg.from_user is not None
    parts = (msg.text or "").split()
    sub = parts[1].lower() if len(parts) > 1 else "help"
    chat_id = msg.chat.id

    if sub == "help":
        await msg.answer(HELP, parse_mode="HTML")
        return

    if sub == "create":
        async with session_scope() as session:
            existing = await repo.active_tournament(session, chat_id)
            if existing is not None:
                await msg.answer("Турнир уже идёт. /tournament top — таблица.")
                return
            games = 5
            points = 3
            if len(parts) > 2 and parts[2].isdigit():
                games = max(1, min(30, int(parts[2])))
            if len(parts) > 3 and parts[3].isdigit():
                points = max(1, min(20, int(parts[3])))
            t = await repo.create_tournament(session, chat_id, msg.from_user.id, games, points)
            await repo.tplayer_add(session, t.id, msg.from_user.id, msg.from_user.full_name)
            table = await _table(t.id)
            sent = await msg.answer(
                f"🏆 <b>Турнир создан!</b> Раундов: {games} · за победу в раунде: +{points}\n\n"
                f"{table}\n\n"
                "Записывайтесь кнопкой. Хост начинает кнопкой «Начать».",
                parse_mode="HTML",
                reply_markup=kb.tournament_kb(can_start=True),
            )
            t.msg_id = sent.message_id
        return

    if sub == "join":
        await _join(msg.from_user.id, msg.from_user.full_name, chat_id, msg)
        return

    if sub == "leave":
        await _leave(msg.from_user.id, chat_id, msg)
        return

    if sub == "top":
        async with session_scope() as session:
            t = await repo.active_tournament(session, chat_id)
            if t is None:
                finished = await _finished_tournament(session, chat_id)
            else:
                finished = None
        if t is None and finished is None:
            await msg.answer("Турнира нет. Создайте: /tournament create")
            return
        tid = t.id if t is not None else finished  # type: ignore[assignment]
        table = await _table(tid)  # type: ignore[arg-type]
        await msg.answer(f"🏆 <b>Таблица турнира:</b>\n\n{table}", parse_mode="HTML")
        return

    if sub == "start":
        async with session_scope() as session:
            t = await repo.active_tournament(session, chat_id)
            if t is None or t.status != "lobby":
                await msg.answer("Нет турнира в статусе ожидания.")
                return
            if t.host_id != msg.from_user.id:
                await msg.answer("Начать может только хост.")
                return
            players = await repo.tournament_players(session, t.id)
            if len(players) < GameSettings().min_players:
                await msg.answer(
                    f"Нужно минимум {GameSettings().min_players} участников."
                )
                return
            t.status = "playing"
            t.round_no = 0
            msg_id = t.msg_id
        try:
            if msg_id:
                await msg.bot.edit_message_reply_markup(
                    chat_id=chat_id, message_id=msg_id, reply_markup=None
                )
        except TelegramBadRequest:
            pass
        await msg.answer(
            "🏁 Турнир начинается! Раунд 1.\nСобирайте партию: /mafia",
            parse_mode="HTML",
        )
        return

    if sub == "cancel":
        async with session_scope() as session:
            t = await repo.active_tournament(session, chat_id)
            if t is None:
                await msg.answer("Нет активного турнира.")
                return
            if t.host_id != msg.from_user.id:
                await msg.answer("Отменить может только хост.")
                return
            t.status = "cancelled"
        await msg.answer("✖️ Турнир отменён.")
        return

    await msg.answer(HELP, parse_mode="HTML")


async def _finished_tournament(session, chat_id: int) -> int | None:
    from sqlalchemy import select

    from mafia.db.models import Tournament

    rows = (
        await session.execute(
            select(Tournament.id)
            .where(Tournament.chat_id == chat_id, Tournament.status == "finished")
            .order_by(Tournament.id.desc())
            .limit(1)
        )
    ).scalars()
    first = list(rows)
    return first[0] if first else None


async def _join(user_id: int, name: str, chat_id: int, target) -> None:
    async with session_scope() as session:
        t = await repo.active_tournament(session, chat_id)
        if t is None or t.status != "lobby":
            await target.answer("Сейчас нельзя записаться (нет открытого турнира).")
            return
        await repo.tplayer_add(session, t.id, user_id, name)
        t_id, msg_id = t.id, t.msg_id
    await target.answer("✅ Вы в турнире!")
    if msg_id:
        table = await _table(t_id)
        try:
            await target.bot.edit_message_text(
                f"🏆 <b>Турнир</b>\n\n{table}",
                chat_id=chat_id,
                message_id=msg_id,
                parse_mode="HTML",
                reply_markup=kb.tournament_kb(can_start=True),
            )
        except TelegramBadRequest:
            pass


async def _leave(user_id: int, chat_id: int, target) -> None:
    async with session_scope() as session:
        t = await repo.active_tournament(session, chat_id)
        if t is None or t.status != "lobby":
            await target.answer("Сейчас нельзя выйти.")
            return
        await repo.tplayer_remove(session, t.id, user_id)
        t_id, msg_id = t.id, t.msg_id
    await target.answer("Вы вышли из турнира.")
    if msg_id:
        table = await _table(t_id)
        try:
            await target.bot.edit_message_text(
                f"🏆 <b>Турнир</b>\n\n{table}",
                chat_id=chat_id,
                message_id=msg_id,
                parse_mode="HTML",
                reply_markup=kb.tournament_kb(can_start=True),
            )
        except TelegramBadRequest:
            pass


@router.callback_query(lambda c: c.data in ("tr:join", "tr:leave", "tr:start"))
async def cb_tournament(cb: CallbackQuery) -> None:
    assert cb.data and cb.from_user and cb.message
    chat_id = cb.message.chat.id
    if cb.data == "tr:join":
        async with session_scope() as session:
            t = await repo.active_tournament(session, chat_id)
        if t is None or t.status != "lobby":
            await cb.answer("Запись закрыта", show_alert=True)
            return
        await _join(cb.from_user.id, cb.from_user.full_name, chat_id, cb.message)
        return
    if cb.data == "tr:leave":
        async with session_scope() as session:
            t = await repo.active_tournament(session, chat_id)
        if t is None or t.status != "lobby":
            await cb.answer("Запись закрыта", show_alert=True)
            return
        await _leave(cb.from_user.id, chat_id, cb.message)
        return
    # tr:start
    async with session_scope() as session:
        t = await repo.active_tournament(session, chat_id)
        if t is None or t.status != "lobby":
            await cb.answer("Турнир не в статусе ожидания", show_alert=True)
            return
        if t.host_id != cb.from_user.id:
            await cb.answer("Только хост", show_alert=True)
            return
        players = await repo.tournament_players(session, t.id)
        if len(players) < GameSettings().min_players:
            await cb.answer(
                f"Нужно минимум {GameSettings().min_players} участников", show_alert=True
            )
            return
        t.status = "playing"
        msg_id = t.msg_id
    if msg_id:
        try:
            await cb.bot.edit_message_reply_markup(
                chat_id=chat_id, message_id=msg_id, reply_markup=None
            )
        except TelegramBadRequest:
            pass
    await cb.answer("Турнир стартует!")
    await cb.message.answer("🏁 Турнир начинается! Раунд 1. Собирайте: /mafia")
