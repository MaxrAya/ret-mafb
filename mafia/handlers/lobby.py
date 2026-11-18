from __future__ import annotations

import asyncio
import html
import time

from aiogram import Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from mafia.db import repo
from mafia.db.session import session_scope
from mafia.game.roles import GameSettings, RolePoolError, auto_role_counts
from mafia.runner import Runner
from mafia.ui import keyboards as kb

router = Router(name="lobby")

NUM_ADJ = {
    "min": (4, 10, 1),
    "max": (5, 20, 1),
    "discuss": (30, 300, 30),
    "vote": (30, 240, 30),
    "night": (20, 180, 10),
}

TOGGLES = {
    "rated": ("rated", "Рейтинг"),
    "anon": ("anonymous_vote", "Анонимность"),
    "don": ("use_don", "Дон"),
    "godfather": ("use_godfather", "Сильный мафиози"),
    "sheriff": ("use_sheriff", "Шериф"),
    "doctor": ("use_doctor", "Доктор"),
    "clown": ("use_clown", "Клоун"),
    "hunter": ("use_hunter", "Охотник"),
}

PRESETS: dict[str, dict[str, int]] = {
    "fast": {"min_players": 4, "max_players": 10, "discuss_s": 30, "vote_s": 30, "night_s": 30},
    "classic": {"min_players": 5, "max_players": 15, "discuss_s": 120, "vote_s": 90, "night_s": 60},
    "long": {"min_players": 7, "max_players": 20, "discuss_s": 180, "vote_s": 120, "night_s": 90},
}


def esc(text: str | None) -> str:
    return html.escape(text or "")


_rights_cool: dict[int, float] = {}


async def _check_rights(msg: Message) -> None:
    chat_id = msg.chat.id
    now = time.time()
    if _rights_cool.get(chat_id, 0) + 3600 > now:
        return
    _rights_cool[chat_id] = now
    try:
        member = await msg.bot.get_chat_member(chat_id, msg.bot.id)
    except TelegramAPIError:
        return
    can_restrict = bool(getattr(member, "can_restrict_members", False))
    can_delete = bool(getattr(member, "can_delete_messages", False))
    if not (can_restrict and can_delete):
        await msg.answer(
            "⚠️ Выдайте боту права администратора:\n"
            "• Ограничение участников (мьют)\n"
            "• Удаление сообщений (запрет медиа и ночная тишина)\n\n"
            "Без них партия идёт, но без блокировок."
        )


def lobby_text(
    host_name: str, players: list[tuple[str, str]], s: GameSettings, is_host: bool
) -> str:
    lines = ["🎲 <b>Лобби Мафии</b>", f"Хост: <b>{esc(host_name)}</b>", ""]
    if players:
        lines.append(f"Игроки ({len(players)}):")
        for i, (_, name) in enumerate(players, 1):
            lines.append(f"{i}. {esc(name)}")
    else:
        lines.append("Пока никто не вошёл — будьте первым!")
    lines.append("")
    lines.append(
        f"⚙ {s.min_players}–{s.max_players} игроков · обсуждение {s.discuss_s}с · "
        f"голосование {s.vote_s}с · ночь {s.night_s}с"
    )
    flags = []
    flags.append("⭐ рейтинг" if s.rated else "без рейтинга")
    flags.append("🙈 аноним" if s.anonymous_vote else "открытые голоса")
    roles = ["дон" if s.use_don else "", "сил. мафиози" if s.use_godfather else "",
             "шериф" if s.use_sheriff else "", "доктор" if s.use_doctor else "",
             "клоун" if s.use_clown else "",              "охотник" if s.use_hunter else ""]
    flags.append("роли: " + ", ".join(r for r in roles if r))
    lines.append(" · ".join(flags))
    if is_host:
        lines.append("\nВы хост — настройте партию кнопками и нажмите «Начать».")
    return "\n".join(lines)


def settings_text(s: GameSettings) -> str:
    roles_on = sum(
        [
            s.use_don,
            s.use_godfather,
            s.use_sheriff,
            s.use_doctor,
            s.use_clown,
            s.use_hunter,
        ]
    )
    return (
        "⚙️ <b>Настройки лобби</b>\n\n"
        f"👥 Игроков: {s.min_players}–{s.max_players} · "
        f"⏱ обсуждение {s.discuss_s}с · голосование {s.vote_s}с · ночь {s.night_s}с\n"
        f"⭐ Рейтинг: {'вкл' if s.rated else 'выкл'} · "
        f"🙈 Анонимность: {'вкл' if s.anonymous_vote else 'выкл'}\n"
        f"🎭 Ролей включено: {roles_on}/6\n\n"
        "Кнопки −/+ меняют значение.\n"
        "✅ — включить, ❌ — выключить роль.\n"
        "Пресеты — быстрый набор настроек."
    )


async def _edit(bot, chat_id: int, msg_id: int, text: str, markup) -> None:
    try:
        await bot.edit_message_text(
            text, chat_id=chat_id, message_id=msg_id,
            parse_mode="HTML", reply_markup=markup,
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


async def _render(
    bot, chat_id: int, session, viewer_id: int
) -> tuple[str, object] | None:
    lobby = await repo.get_lobby(session, chat_id)
    if lobby is None:
        return None
    rows = await repo.lobby_players(session, chat_id)
    settings = GameSettings.from_json(lobby.settings_json)
    is_host = lobby.host_id == viewer_id
    host_name = next((r.name for r in rows if r.user_id == lobby.host_id), "")
    players = [(str(r.user_id), r.name) for r in rows]
    text = lobby_text(host_name, players, settings, is_host)
    return text, kb.lobby_kb(has_host=True) if is_host else kb.lobby_kb(has_host=False)


async def _refresh(bot, chat_id: int, viewer_id: int) -> None:
    async with session_scope() as session:
        lobby = await repo.get_lobby(session, chat_id)
        if lobby is None:
            return
        rendered = await _render(bot, chat_id, session, viewer_id)
        msg_id = lobby.msg_id
    if rendered and msg_id:
        text, markup = rendered
        await _edit(bot, chat_id, msg_id, text, markup)


# ---------- command ----------


async def _notify_subs(msg: Message) -> None:
    async with session_scope() as session:
        subs = await repo.all_subs(session)
    if not subs:
        return
    title = msg.chat.title or msg.chat.full_name or "группа"
    text = f"📢 В чате «{esc(title)}» собирают партию! Открой бота и жми /mafia"
    sender = msg.from_user.id if msg.from_user else 0
    for uid in subs:
        if uid == sender:
            continue
        try:
            await msg.bot.send_message(uid, text)
        except TelegramAPIError:
            continue
        await asyncio.sleep(0.05)


@router.message(Command("mafia"))
async def cmd_mafia(msg: Message, runner: Runner) -> None:
    if msg.chat.type not in ("group", "supergroup"):
        await msg.answer("Пиши /mafia прямо в группе 😉")
        return
    assert msg.from_user is not None
    chat_id = msg.chat.id
    await _check_rights(msg)
    async with session_scope() as session:
        active = await repo.active_match_in_chat(session, chat_id)
        if active:
            await msg.answer("Партия уже идёт. Дождитесь конца — /game покажет состояние.")
            return
        if await repo.user_in_active_match(session, msg.from_user.id):
            await msg.answer("Вы уже играете в другой партии.")
            return
        tournament = await repo.active_tournament(session, chat_id)
        attach_id: int | None = None
        if tournament is not None and tournament.status == "playing":
            parts = await repo.tournament_players(session, tournament.id)
            if not any(p.user_id == msg.from_user.id for p in parts):
                await msg.answer("Идёт турнир — в партии играют только его участники.")
                return
            attach_id = tournament.id
        lobby = await repo.get_lobby(session, chat_id)
        created_new = lobby is None
        if lobby is None:
            settings = GameSettings()
            lobby = await repo.create_lobby(
                session, chat_id, msg.from_user.id, settings, attach_id
            )
            await repo.lobby_add(
                session, chat_id, msg.from_user.id, msg.from_user.full_name
            )
            settings_obj = settings
        else:
            settings_obj = GameSettings.from_json(lobby.settings_json)
            await repo.lobby_add(
                session, chat_id, msg.from_user.id, msg.from_user.full_name
            )
        rows = await repo.lobby_players(session, chat_id)
        host_name = next(
            (r.name for r in rows if r.user_id == lobby.host_id),
            msg.from_user.full_name,
        )
        players = [(str(r.user_id), r.name) for r in rows]
        is_host = lobby.host_id == msg.from_user.id
        text = lobby_text(host_name, players, settings_obj, is_host)
        markup = kb.lobby_kb(has_host=True) if is_host else kb.lobby_kb(has_host=False)
        sent = await msg.answer(text, parse_mode="HTML", reply_markup=markup)
        lobby.msg_id = sent.message_id
    if created_new:
        await _notify_subs(msg)


# ---------- callbacks ----------


@router.callback_query(lambda c: c.data == "lb:join")
async def cb_join(cb: CallbackQuery, runner: Runner) -> None:
    assert cb.from_user and cb.message
    chat_id = cb.message.chat.id
    async with session_scope() as session:
        lobby = await repo.get_lobby(session, chat_id)
        if lobby is None:
            await cb.answer("Лобби закрыто", show_alert=True)
            return
        if await repo.user_in_active_match(session, cb.from_user.id):
            await cb.answer("Вы уже в активной партии", show_alert=True)
            return
        other = await repo.user_in_any_lobby(session, cb.from_user.id)
        if other is not None and other != chat_id:
            await cb.answer("Вы уже в лобби другой группы", show_alert=True)
            return
        rows = await repo.lobby_players(session, chat_id)
        settings = GameSettings.from_json(lobby.settings_json)
        if any(r.user_id == cb.from_user.id for r in rows):
            await cb.answer("Вы уже в лобби", show_alert=True)
            return
        if len(rows) >= settings.max_players:
            await cb.answer("Лобби заполнено", show_alert=True)
            return
        if lobby.tournament_id is not None:
            parts = await repo.tournament_players(session, lobby.tournament_id)
            if not any(p.user_id == cb.from_user.id for p in parts):
                await cb.answer("Только участники турнира", show_alert=True)
                return
        await repo.lobby_add(session, chat_id, cb.from_user.id, cb.from_user.full_name)
        await cb.answer("Вы в игре! Ждём остальных.")
    await _refresh(cb.bot, chat_id, cb.from_user.id)


@router.callback_query(lambda c: c.data == "lb:leave")
async def cb_leave(cb: CallbackQuery) -> None:
    assert cb.from_user and cb.message
    chat_id = cb.message.chat.id
    async with session_scope() as session:
        lobby = await repo.get_lobby(session, chat_id)
        if lobby is None:
            await cb.answer("Лобби закрыто", show_alert=True)
            return
        await repo.lobby_remove(session, chat_id, cb.from_user.id)
        rows = await repo.lobby_players(session, chat_id)
        if not rows:
            await repo.delete_lobby(session, chat_id)
            await cb.answer("Лобби закрыто")
            await _edit(
                cb.bot, chat_id, lobby.msg_id or 0,
                "✖️ Лобби закрыто.", None,
            )
            return
        if lobby.host_id == cb.from_user.id:
            lobby.host_id = rows[0].user_id
        await cb.answer("Вы вышли")
    await _refresh(cb.bot, chat_id, cb.from_user.id)


@router.callback_query(lambda c: c.data == "lb:cancel")
async def cb_cancel(cb: CallbackQuery) -> None:
    assert cb.from_user and cb.message
    chat_id = cb.message.chat.id
    async with session_scope() as session:
        lobby = await repo.get_lobby(session, chat_id)
        if lobby is None:
            await cb.answer("Лобби уже закрыто", show_alert=True)
            return
        if lobby.host_id != cb.from_user.id:
            await cb.answer("Только хост может отменить", show_alert=True)
            return
        msg_id = lobby.msg_id
        await repo.delete_lobby(session, chat_id)
    await cb.answer("Лобби отменено")
    if msg_id:
        await _edit(cb.bot, chat_id, msg_id, "✖️ Лобби отменено хостом.", None)


@router.callback_query(lambda c: c.data == "lb:start")
async def cb_start(cb: CallbackQuery, runner: Runner) -> None:
    assert cb.from_user and cb.message
    chat_id = cb.message.chat.id
    async with session_scope() as session:
        lobby = await repo.get_lobby(session, chat_id)
        if lobby is None:
            await cb.answer("Лобби закрыто", show_alert=True)
            return
        if lobby.host_id != cb.from_user.id:
            await cb.answer("Только хост может начать", show_alert=True)
            return
        rows = await repo.lobby_players(session, chat_id)
        settings = GameSettings.from_json(lobby.settings_json)
        n = len(rows)
        if n < settings.min_players:
            await cb.answer(
                f"Нужно минимум {settings.min_players} игроков (сейчас {n})",
                show_alert=True,
            )
            return
        if n > settings.max_players:
            await cb.answer(
                f"Слишком много игроков (максимум {settings.max_players})", show_alert=True
            )
            return
        try:
            auto_role_counts(n, settings)
        except RolePoolError as e:
            await cb.answer(str(e), show_alert=True)
            return
        players = [(r.user_id, r.name) for r in rows]
        tournament_id = lobby.tournament_id
        rated = settings.rated
        host_id = lobby.host_id
        msg_id = lobby.msg_id
        await repo.delete_lobby(session, chat_id)

    try:
        await runner.start_game(chat_id, host_id, players, settings, rated, tournament_id)
    except RolePoolError as e:
        await cb.answer(str(e), show_alert=True)
        return
    await cb.answer("Игра началась!")
    if msg_id:
        try:
            await cb.bot.edit_message_reply_markup(
                chat_id=chat_id, message_id=msg_id, reply_markup=None
            )
        except TelegramBadRequest:
            pass


# ---------- settings ----------


async def _settings_view(cb: CallbackQuery, settings: GameSettings, msg_id: int) -> None:
    await _edit(
        cb.bot, cb.message.chat.id, msg_id,
        settings_text(settings), kb.settings_kb(settings),
    )


@router.callback_query(lambda c: c.data == "st:menu")
async def st_menu(cb: CallbackQuery) -> None:
    assert cb.from_user and cb.message
    async with session_scope() as session:
        lobby = await repo.get_lobby(session, cb.message.chat.id)
        if lobby is None:
            await cb.answer("Лобби закрыто", show_alert=True)
            return
        if lobby.host_id != cb.from_user.id:
            await cb.answer("Настройки доступны хосту", show_alert=True)
            return
        settings = GameSettings.from_json(lobby.settings_json)
        msg_id = lobby.msg_id or 0
    await cb.answer()
    await _settings_view(cb, settings, msg_id)


@router.callback_query(lambda c: c.data == "st:back")
async def st_back(cb: CallbackQuery) -> None:
    assert cb.from_user and cb.message
    await cb.answer()
    await _refresh(cb.bot, cb.message.chat.id, cb.from_user.id)


@router.callback_query(lambda c: c.data == "st:noop")
async def st_noop(cb: CallbackQuery) -> None:
    await cb.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("st:tg:"))
async def st_toggle(cb: CallbackQuery) -> None:
    assert cb.from_user and cb.message and cb.data
    key = cb.data.split(":")[2]
    if key not in TOGGLES:
        await cb.answer("Неизвестная настройка", show_alert=True)
        return
    chat_id = cb.message.chat.id
    async with session_scope() as session:
        lobby = await repo.get_lobby(session, chat_id)
        if lobby is None:
            await cb.answer("Лобби закрыто", show_alert=True)
            return
        if lobby.host_id != cb.from_user.id:
            await cb.answer("Только хост", show_alert=True)
            return
        settings = GameSettings.from_json(lobby.settings_json)
        attr = TOGGLES[key][0]
        setattr(settings, attr, not getattr(settings, attr))
        if settings.min_players > settings.max_players:
            settings.max_players = settings.min_players
        lobby.settings_json = settings.to_json()
        msg_id = lobby.msg_id or 0
    await cb.answer("Сохранено")
    await _settings_view(cb, settings, msg_id)


async def _adjust(cb: CallbackQuery, key: str, direction: int) -> None:
    assert cb.from_user and cb.message and cb.data
    if key not in NUM_ADJ:
        await cb.answer("Неизвестная настройка", show_alert=True)
        return
    lo, hi, step = NUM_ADJ[key]
    chat_id = cb.message.chat.id
    async with session_scope() as session:
        lobby = await repo.get_lobby(session, chat_id)
        if lobby is None:
            await cb.answer("Лобби закрыто", show_alert=True)
            return
        if lobby.host_id != cb.from_user.id:
            await cb.answer("Только хост", show_alert=True)
            return
        settings = GameSettings.from_json(lobby.settings_json)
        attr = {
            "min": "min_players",
            "max": "max_players",
            "discuss": "discuss_s",
            "vote": "vote_s",
            "night": "night_s",
        }[key]
        value = getattr(settings, attr) + direction * step
        if value > hi:
            value = lo
        elif value < lo:
            value = hi
        setattr(settings, attr, value)
        if settings.min_players > settings.max_players:
            if key == "min":
                settings.max_players = settings.min_players
            else:
                settings.min_players = settings.max_players
        lobby.settings_json = settings.to_json()
        msg_id = lobby.msg_id or 0
    await cb.answer("Сохранено")
    await _settings_view(cb, settings, msg_id)


@router.callback_query(lambda c: c.data and c.data.startswith("st:adj:"))
async def st_adj(cb: CallbackQuery) -> None:
    await _adjust(cb, cb.data.split(":")[2], +1)


@router.callback_query(lambda c: c.data and c.data.startswith("st:adjm:"))
async def st_adjm(cb: CallbackQuery) -> None:
    await _adjust(cb, cb.data.split(":")[2], -1)


@router.callback_query(lambda c: c.data and c.data.startswith("st:preset:"))
async def st_preset(cb: CallbackQuery) -> None:
    assert cb.from_user and cb.message and cb.data
    key = cb.data.split(":")[2]
    if key not in PRESETS:
        await cb.answer("Неизвестный пресет", show_alert=True)
        return
    chat_id = cb.message.chat.id
    async with session_scope() as session:
        lobby = await repo.get_lobby(session, chat_id)
        if lobby is None:
            await cb.answer("Лобби закрыто", show_alert=True)
            return
        if lobby.host_id != cb.from_user.id:
            await cb.answer("Только хост", show_alert=True)
            return
        settings = GameSettings.from_json(lobby.settings_json)
        for attr, value in PRESETS[key].items():
            setattr(settings, attr, value)
        lobby.settings_json = settings.to_json()
        msg_id = lobby.msg_id or 0
    await cb.answer("Пресет применён")
    await _settings_view(cb, settings, msg_id)


# ---------- rematch ----------


@router.callback_query(lambda c: c.data and c.data.startswith("rm:"))
async def cb_rematch(cb: CallbackQuery, runner: Runner) -> None:
    assert cb.from_user and cb.message and cb.data
    old_id = int(cb.data.split(":")[1])
    chat_id = cb.message.chat.id
    async with session_scope() as session:
        match = await repo.get_match(session, old_id)
        if match is None or match.chat_id != chat_id:
            await cb.answer("Партия не найдена", show_alert=True)
            return
        if match.status != "finished":
            await cb.answer("Эта партия уже закрыта", show_alert=True)
            return
        if match.tournament_id is not None:
            await cb.answer("Турнир: новая партия через /mafia", show_alert=True)
            return
        if cb.from_user.id != match.host_id:
            await cb.answer("Только хост может начать реванш", show_alert=True)
            return
        if await repo.active_match_in_chat(session, chat_id):
            await cb.answer("Партия уже идёт", show_alert=True)
            return
        if await repo.get_lobby(session, chat_id):
            await cb.answer("Лобби уже открыто: /mafia", show_alert=True)
            return
        rows = await repo.match_players(session, old_id)
        for pr in rows:
            if await repo.user_in_active_match(session, pr.user_id):
                await cb.answer(
                    "Кто-то из игроков уже в другой партии", show_alert=True
                )
                return
        settings = GameSettings.from_json(match.settings_json)
        raw = [(pr.user_id, pr.name) for pr in rows]
        host_id = match.host_id
        rated = bool(match.rated)
    try:
        await runner.start_game(chat_id, host_id, raw, settings, rated, None)
    except RolePoolError as e:
        await cb.answer(str(e), show_alert=True)
        return
    await cb.answer("Реванш! Состав тот же — партия пошла.")
