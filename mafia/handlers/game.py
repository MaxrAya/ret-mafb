from __future__ import annotations

import html
import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from mafia.db import repo
from mafia.db.session import session_scope
from mafia.game import engine
from mafia.game.engine import EditGroup, EngineError, Phase
from mafia.runner import Runner

router = Router(name="game")

PHASE_TITLES = {
    Phase.NIGHT: "🌙 Ночь",
    Phase.DAY_DISCUSS: "☀️ Обсуждение",
    Phase.DAY_VOTE: "🗳 Голосование",
    Phase.HUNTER: "🔫 Охотник стреляет",
}


def _split(cb: CallbackQuery, prefix: str) -> tuple[int, int, int] | None:
    if not cb.data:
        return None
    parts = cb.data.split(":")
    if len(parts) != 4:
        return None
    try:
        return int(parts[1]), int(parts[2]), int(parts[3])
    except ValueError:
        return None


async def _match_guard(cb: CallbackQuery, mid: int) -> tuple[bool, int | None]:
    """Validate callback against its match. Returns (ok, vote_msg_id)."""
    if cb.message is None:
        return False, None
    async with session_scope() as session:
        m = await repo.get_match(session, mid)
        if m is None or m.status != "active":
            await cb.answer("Партия уже закончилась", show_alert=True)
            return False, None
        if m.chat_id != cb.message.chat.id:
            await cb.answer("Не тот чат", show_alert=True)
            return False, None
        return True, m.vote_msg_id


@router.callback_query(lambda c: c.data and c.data.startswith("v:"))
async def cb_vote(cb: CallbackQuery, runner: Runner) -> None:
    parsed = _split(cb, "v")
    if parsed is None:
        await cb.answer("Плохой запрос", show_alert=True)
        return
    mid, day, target_seat = parsed
    ok, vote_msg_id = await _match_guard(cb, mid)
    if not ok:
        return
    now = int(time.time())

    def op(s: engine.GameState) -> list[engine.Effect]:
        if s.day != day or s.phase != Phase.DAY_VOTE:
            raise EngineError("Голосование устарело")
        voter = s.by_user(cb.from_user.id)
        if voter is None:
            raise EngineError("Вы не в игре")
        engine.cast_vote(s, voter.seat, target_seat)
        if vote_msg_id:
            return [
                EditGroup(
                    vote_msg_id,
                    engine.vote_text(s, now),
                    ("vote", str(s.day)),
                )
            ]
        return []

    try:
        state = await runner.run(mid, op)
    except EngineError as e:
        await cb.answer(str(e), show_alert=True)
        return
    if state is None:
        await cb.answer("Партия закончилась", show_alert=True)
        return
    target = state.by_seat(target_seat)
    await cb.answer(f"Ваш голос: {target.name if target else '?'}")


@router.callback_query(lambda c: c.data and c.data.startswith("n:"))
async def cb_night(cb: CallbackQuery, runner: Runner) -> None:
    parsed = _split(cb, "n")
    if parsed is None:
        await cb.answer("Плохой запрос", show_alert=True)
        return
    mid, day, target_seat = parsed
    ok, _ = await _match_guard(cb, mid)
    if not ok:
        return
    now = int(time.time())

    def op(s: engine.GameState) -> list[engine.Effect]:
        if s.day != day or s.phase != Phase.NIGHT:
            raise EngineError("Ночь уже прошла")
        actor = s.by_user(cb.from_user.id)
        if actor is None:
            raise EngineError("Вы не в игре")
        return engine.night_pick(s, actor.seat, target_seat, now)

    try:
        state = await runner.run(mid, op)
    except EngineError as e:
        await cb.answer(str(e), show_alert=True)
        return
    if state is None:
        await cb.answer("Партия закончилась", show_alert=True)
        return
    target = state.by_seat(target_seat)
    await cb.answer(f"Выбрано: {target.name if target else '?'}")


@router.callback_query(lambda c: c.data and c.data.startswith("h:"))
async def cb_hunter(cb: CallbackQuery, runner: Runner) -> None:
    parsed = _split(cb, "h")
    if parsed is None:
        await cb.answer("Плохой запрос", show_alert=True)
        return
    mid, day, target_seat = parsed
    ok, _ = await _match_guard(cb, mid)
    if not ok:
        return
    now = int(time.time())

    def op(s: engine.GameState) -> list[engine.Effect]:
        if s.day != day or s.phase != Phase.HUNTER:
            raise EngineError("Выстрел уже сделан")
        shooter = s.by_user(cb.from_user.id)
        if shooter is None or shooter.seat != s.pending_hunter_seat:
            raise EngineError("Стреляет другой игрок")
        return engine.resolve_hunter(s, target_seat or None, now)

    try:
        state = await runner.run(mid, op)
    except EngineError as e:
        await cb.answer(str(e), show_alert=True)
        return
    if state is None:
        await cb.answer("Партия закончилась", show_alert=True)
        return
    await cb.answer("Решение принято")


@router.message(Command("game"), F.chat.type.in_(["group", "supergroup"]))
async def cmd_game(msg: Message) -> None:
    assert msg.from_user
    async with session_scope() as session:
        mid = await repo.active_match_in_chat(session, msg.chat.id)
        if mid is None:
            await msg.answer("Активной партии нет. Начните: /mafia")
            return
        state = await repo.load_state(session, mid)
    if state is None:
        await msg.answer("Партия не найдена")
        return
    title = PHASE_TITLES.get(state.phase, "Игра окончена")
    alive = state.alive_pairs()
    lines = "\n".join(f"{s}. {html.escape(n)}" for s, n in alive)
    remain = ""
    if state.deadline_ts:
        remain = f"\n⏱ До конца фазы: {max(0, state.deadline_ts - int(time.time()))} с"
    await msg.answer(
        f"<b>{title}</b> · день {state.day}\nЖивые ({len(alive)}):\n{lines}{remain}",
        parse_mode="HTML",
    )


@router.message(Command("skip"), F.chat.type.in_(["group", "supergroup"]))
async def cmd_skip(msg: Message, runner: Runner) -> None:
    assert msg.from_user
    async with session_scope() as session:
        mid = await repo.active_match_in_chat(session, msg.chat.id)
    if mid is None:
        await msg.answer("Нет активной партии")
        return
    now = int(time.time())

    def op(s: engine.GameState) -> list[engine.Effect]:
        if s.host_id != msg.from_user.id:
            raise EngineError("Пропустить фазу может только хост")
        return engine.host_skip(s, now)

    try:
        await runner.run(mid, op)
    except EngineError as e:
        await msg.answer(str(e))
        return
    await msg.answer("⏭ Фаза пропущена хостом.")


@router.message(F.chat.type == "private", F.text, ~F.text.startswith("/"))
async def mafia_relay(msg: Message, runner: Runner) -> None:
    if msg.from_user is None or not msg.text:
        return
    async with session_scope() as session:
        mid = await repo.user_in_active_match(session, msg.from_user.id)
    if mid is None:
        return
    await runner.relay_mafia(mid, msg.from_user.id, msg.text)
