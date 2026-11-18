from __future__ import annotations

import html
from datetime import UTC, datetime, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

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
                        select(User).where(func.lower(User.username) == uname).limit(1)
                    )
                ).scalars().first()
                if user is not None:
                    return user.id, user.full_name
            return 0, arg
        if arg.isdigit():
            uid = int(arg)
            async with session_scope() as session:
                user = await session.get(User, uid)
            return uid, user.full_name if user else arg
    assert msg.from_user is not None
    return msg.from_user.id, msg.from_user.full_name


async def profile_html(
    uid: int, name: str, chat_id: int | None = None
) -> str | None:
    async with session_scope() as session:
        if uid == 0:
            return None
        st = await repo.get_stats(session, uid)
        ach = await repo.get_achievements(session, uid)
        chat_rating = None
        if chat_id is not None:
            cs = await session.get(ChatStats, (uid, chat_id))
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
    return "\n".join(lines)


@router.message(Command("profile"))
async def cmd_profile(msg: Message) -> None:
    uid, name = await _resolve_username(msg)
    if uid == 0:
        await msg.answer("Не нашёл такого игрока.")
        return
    chat_id = (
        msg.chat.id
        if msg.chat.type in ("group", "supergroup")
        else None
    )
    text = await profile_html(uid, name, chat_id)
    if text is None:
        await msg.answer("Не нашёл такого игрока.")
        return
    await msg.answer(text, parse_mode="HTML")


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
    other = "Топ чата" if where == "global" else "Глобальный топ"
    cb = f"top:chat:{chat_id}" if where == "global" else "top:global"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 Неделя", callback_data="top:period:week"),
                InlineKeyboardButton(text="📅 Месяц", callback_data="top:period:month"),
                InlineKeyboardButton(text="🌍 Всё время", callback_data="top:global"),
            ],
            [InlineKeyboardButton(text=other, callback_data=cb)],
        ]
    )


PERIOD_TITLES = {
    "week": "📅 <b>Топ за неделю</b>",
    "month": "📅 <b>Топ за месяц</b>",
}


async def _period_top(days: int) -> str:
    since = datetime.now(UTC) - timedelta(days=days)
    async with session_scope() as session:
        rows = await repo.top_period(session, since)
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (uid, delta, games) in enumerate(rows, 1):
            prefix = medals[i - 1] if i <= 3 else f"{i}."
            user = await session.get(User, uid)
            name = user.full_name if user else str(uid)
            sign = f"+{delta}" if delta > 0 else str(delta)
            lines.append(f"{prefix} {esc(name)} — ⭐{sign} · {games} игр")
    return "\n".join(lines) if lines else "Пока пусто."


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
    return bool(
        c.data
        and (
            c.data == "top:global"
            or c.data.startswith("top:chat:")
            or c.data.startswith("top:period:")
        )
    )


@router.callback_query(_is_top_cb)
async def cb_top(cb: CallbackQuery) -> None:
    assert cb.data and cb.message
    chat_id = cb.message.chat.id
    if cb.data.startswith("top:period:"):
        period = cb.data.split(":")[2]
        days = 7 if period == "week" else 30
        body = await _period_top(days)
        text = f"{PERIOD_TITLES[period]}\n\n" + body
        kb = _top_kb(chat_id, "global")
    elif cb.data == "top:global":
        body = await _global_top()
        text = "🌍 <b>Глобальный рейтинг</b>\n\n" + body
        kb = _top_kb(chat_id, "global")
    else:
        top_chat_id = int(cb.data.split(":")[2])
        body = await _chat_top(top_chat_id)
        text = "🏘 <b>Рейтинг этого чата</b>\n\n" + body
        kb = _top_kb(top_chat_id, "chat")
    try:
        await cb.message.edit_text(
            text, parse_mode="HTML", reply_markup=kb
        )
    except Exception:
        pass
    await cb.answer()


async def ach_html(uid: int, name: str) -> str | None:
    async with session_scope() as session:
        if uid == 0:
            return None
        owned = await repo.get_achievements(session, uid)
    lines = [f"🏆 <b>Достижения — {esc(name)}</b> ({len(owned)}/{len(ACHIEVEMENTS)})\n"]
    for a in ACHIEVEMENTS:
        if a.key in owned:
            lines.append(f"✅ {a.emoji} <b>{a.title}</b> — {a.desc}")
        else:
            lines.append(f"🔒 {a.emoji} {a.title}")
    return "\n".join(lines)


@router.message(Command("achievements"))
async def cmd_achievements(msg: Message) -> None:
    uid, name = await _resolve_username(msg)
    text = await ach_html(uid, name)
    if text is None:
        await msg.answer("Не нашёл такого игрока.")
        return
    await msg.answer(text, parse_mode="HTML")


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


@router.message(Command("subscribe"))
async def cmd_subscribe(msg: Message) -> None:
    assert msg.from_user is not None
    async with session_scope() as session:
        await repo.add_sub(session, msg.from_user.id)
    await msg.answer(
        "🔔 Подписка включена. Напишу в ЛС, когда в группе начнут собирать партию.\n"
        "Отключить: /unsubscribe"
    )


@router.message(Command("unsubscribe"))
async def cmd_unsubscribe(msg: Message) -> None:
    assert msg.from_user is not None
    async with session_scope() as session:
        await repo.del_sub(session, msg.from_user.id)
    await msg.answer("🔕 Подписка отключена.")
