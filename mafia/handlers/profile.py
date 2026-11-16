from __future__ import annotations

import html

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from mafia.db import repo
from mafia.db.models import ChatStats, PlayerStats, User
from mafia.db.session import session_scope
from mafia.game.achievements import ACHIEVEMENTS
from mafia.ui.texts import WINNER_TITLE

router = Router(name="profile")


def esc(text: str | None) -> str:
    return html.escape(text or "")


async def _resolve_username(msg: Message) -> tuple[int, str]:
    if msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        return u.id, u.full_name
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) > 1:
        arg = parts[1].strip()
        if arg.startswith("@"):
            uname = arg[1:].lower()
            async with session_scope() as session:
                user = (
                    await session.execute(
                        select(User).where(User.username.isnot(None))
                    )
                ).scalars()
                for u in user:
                    if (u.username or "").lower() == uname:
                        return u.id, u.full_name
            return 0, arg
        if arg.isdigit():
            uid = int(arg)
            async with session_scope() as session:
                user = await session.get(User, uid)
            return uid, user.full_name if user else arg
    assert msg.from_user is not None
    return msg.from_user.id, msg.from_user.full_name


@router.message(Command("profile"))
async def cmd_profile(msg: Message) -> None:
    uid, name = await _resolve_username(msg)
    async with session_scope() as session:
        if uid == 0:
            await msg.answer("Не нашёл такого игрока.")
            return
        st = await repo.get_stats(session, uid)
        ach = await repo.get_achievements(session, uid)
        chat_rating = None
        if msg.chat.type in ("group", "supergroup"):
            cs = await session.get(ChatStats, (uid, msg.chat.id))
            if cs is not None and cs.games:
                chat_rating = cs.rating
        total_ach = len(ACHIEVEMENTS)
    winrate = round(100 * st.wins / st.games) if st.games else 0
    lines = [
        f"👤 <b>{esc(name)}</b>",
        f"⭐ Рейтинг: <b>{st.rating}</b>",
    ]
    if chat_rating is not None:
        lines.append(f"🏷 Рейтинг в этом чате: {chat_rating}")
    lines += [
        f"🎲 Партий: {st.games} · Побед: {st.wins} ({winrate}%)",
        f"🔥 Серия: {st.streak} · Рекорд: {st.best_streak}",
        f"🔪 Побед за мафию: {st.wins_mafia} · 🏙 за город: {st.wins_town} · "
        f"🤡 за клоуна: {st.wins_clown}",
        f"🏆 Достижений: {len(ach)}/{total_ach}",
    ]
    await msg.answer("\n".join(lines), parse_mode="HTML")


def _top_rows(rows: list[tuple[str, PlayerStats]]) -> str:
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (name, st) in enumerate(rows, 1):
        prefix = medals[i - 1] if i <= 3 else f"{i}."
        winrate = round(100 * st.wins / st.games) if st.games else 0
        lines.append(
            f"{prefix} {esc(name)} — ⭐{st.rating} · {st.games} игр · {winrate}% побед"
        )
    return "\n".join(lines) if lines else "Пока пусто."


async def _global_top() -> str:
    async with session_scope() as session:
        stats_rows = (
            await session.execute(
                select(PlayerStats)
                .where(PlayerStats.games > 0)
                .order_by(PlayerStats.rating.desc())
                .limit(10)
            )
        ).scalars()
        stats = list(stats_rows)
        out: list[tuple[str, PlayerStats]] = []
        for st in stats:
            user = await session.get(User, st.user_id)
            out.append((user.full_name if user else str(st.user_id), st))
    return _top_rows(out)


async def _chat_top(chat_id: int) -> str:
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(ChatStats)
                .where(ChatStats.chat_id == chat_id, ChatStats.games > 0)
                .order_by(ChatStats.rating.desc())
                .limit(10)
            )
        ).scalars()
        out: list[tuple[str, PlayerStats]] = []
        for cs in rows:
            user = await session.get(User, cs.user_id)
            st = PlayerStats(
                user_id=cs.user_id,
                rating=cs.rating,
                games=cs.games,
                wins=cs.wins,
            )
            out.append((user.full_name if user else str(cs.user_id), st))
    return _top_rows(out)


def _top_kb(chat_id: int, where: str):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    other = "Топ чата" if where == "global" else "Глобальный топ"
    cb = f"top:chat:{chat_id}" if where == "global" else "top:global"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=other, callback_data=cb)]
        ]
    )


@router.message(Command("top"))
async def cmd_top(msg: Message) -> None:
    body = await _global_top()
    chat_id = msg.chat.id
    await msg.answer(
        "🌍 <b>Глобальный рейтинг</b>\n\n" + body,
        parse_mode="HTML",
        reply_markup=_top_kb(chat_id, "global"),
    )


def _is_top_cb(c) -> bool:
    return bool(c.data and (c.data == "top:global" or c.data.startswith("top:chat:")))


@router.callback_query(_is_top_cb)
async def cb_top(cb: CallbackQuery) -> None:
    assert cb.data and cb.message
    if cb.data == "top:global":
        body = await _global_top()
        text = "🌍 <b>Глобальный рейтинг</b>\n\n" + body
        kb = _top_kb(cb.message.chat.id, "global")
    else:
        chat_id = int(cb.data.split(":")[2])
        body = await _chat_top(chat_id)
        text = "🏘 <b>Рейтинг этого чата</b>\n\n" + body
        kb = _top_kb(chat_id, "chat")
    try:
        await cb.message.edit_text(
            text, parse_mode="HTML", reply_markup=kb
        )
    except Exception:
        pass
    await cb.answer()


@router.message(Command("achievements"))
async def cmd_achievements(msg: Message) -> None:
    uid, name = await _resolve_username(msg)
    async with session_scope() as session:
        if uid == 0:
            await msg.answer("Не нашёл такого игрока.")
            return
        owned = await repo.get_achievements(session, uid)
    lines = [f"🏆 <b>Достижения — {esc(name)}</b> ({len(owned)}/{len(ACHIEVEMENTS)})\n"]
    for a in ACHIEVEMENTS:
        if a.key in owned:
            lines.append(f"✅ {a.emoji} <b>{a.title}</b> — {a.desc}")
        else:
            lines.append(f"🔒 {a.emoji} {a.title}")
    await msg.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("matches"))
async def cmd_matches(msg: Message) -> None:
    if msg.chat.type not in ("group", "supergroup"):
        await msg.answer("Команда работает в группе.")
        return
    async with session_scope() as session:
        rows = await repo.recent_matches(session, msg.chat.id, 5)
        blocks = []
        for m in rows:
            players = await repo.match_players(session, m.id)
            title = WINNER_TITLE.get(m.winner or "", "Итог")
            date = m.ended_at.strftime("%d.%m %H:%M") if m.ended_at else ""
            blocks.append(
                f"<b>#{m.id}</b> · {title} · {len(players)} игроков · {date}"
            )
    if not blocks:
        await msg.answer("Здесь ещё не играли. Начните первую партию: /mafia")
        return
    await msg.answer(
        "📻 <b>Последние партии чата:</b>\n\n" + "\n".join(blocks),
        parse_mode="HTML",
    )
