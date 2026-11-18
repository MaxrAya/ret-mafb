from __future__ import annotations

import asyncio
import html
import logging
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import ChatPermissions, InlineKeyboardMarkup

from mafia.db import repo
from mafia.db.session import session_scope
from mafia.game import achievements as ach_mod
from mafia.game import engine, rating
from mafia.game.engine import (
    EditGroup,
    EditPM,
    Effect,
    GameState,
    GPlayer,
    Mute,
    Phase,
    SendGroup,
    SendPM,
    Unmute,
)
from mafia.game.roles import GameSettings, Role, Team
from mafia.ui import keyboards as kb
from mafia.ui import texts as T

log = logging.getLogger("runner")

FULL_PERMS = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_invite_users=True,
)

GIF_TAG_KIND = {
    "start": "start",
    "night_banner": "night",
    "day_banner": "day",
    "vote": "vote",
    "end": "end",
}


def mafia_line(sender: GPlayer, text: str) -> str:
    label = "Дон" if sender.role == Role.DON else "Мафия"
    return f"{label}: {html.escape(sender.name)} — {html.escape(text)}"


class Runner:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._chat_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._gifs: dict[int, dict[str, str]] = {}
        self._mafia_lines: dict[int, tuple[int, list[str]]] = {}
        self._mafia_msgs: dict[tuple[int, int], int] = {}

    def lock(self, match_id: int) -> asyncio.Lock:
        return self._locks[match_id]

    def chat_lock(self, chat_id: int) -> asyncio.Lock:
        return self._chat_locks[chat_id]

    # ---------- gif cache ----------

    async def gifs_for(self, chat_id: int) -> dict[str, str]:
        if chat_id not in self._gifs:
            async with session_scope() as session:
                self._gifs[chat_id] = await repo.get_gifs(session, chat_id)
        return self._gifs[chat_id]

    def gif_put(self, chat_id: int, kind: str, file_id: str) -> None:
        self._gifs.setdefault(chat_id, {})[kind] = file_id

    # ---------- generic run ----------

    async def run(
        self,
        match_id: int,
        op: Callable[[GameState], list[Effect]],
    ) -> GameState | None:
        async with self.lock(match_id):
            async with session_scope() as session:
                state = await repo.load_state(session, match_id)
                if state is None:
                    return None
                try:
                    effects = op(state)
                except engine.EngineError:
                    raise
                await repo.save_state(session, state)
                ended_now = state.phase == Phase.ENDED
            await self._apply(state, effects)
            if ended_now:
                await self.finalize(state)
            return state

    # ---------- lifecycle ----------

    async def start_game(
        self,
        chat_id: int,
        host_id: int,
        raw_players: list[tuple[int, str]],
        settings: GameSettings,
        rated: bool,
        tournament_id: int | None,
    ) -> int:
        now = int(time.time())
        async with session_scope() as session:
            match = await repo.create_match(
                session, chat_id, host_id, settings, rated, tournament_id
            )
            match_id = match.id
        state, effects = engine.new_game(
            match_id, chat_id, host_id, raw_players, settings, rated,
            tournament_id, now,
        )
        async with self.lock(match_id):
            async with session_scope() as session:
                await repo.save_state(session, state)
            await self._apply(state, effects)
            async with session_scope() as session:
                await repo.save_state(session, state)
        return match_id

    async def abort(self, match_id: int, reason: str) -> None:
        async with self.lock(match_id):
            async with session_scope() as session:
                state = await repo.load_state(session, match_id)
                if state is None:
                    return
                effects: list[Effect] = [
                    SendGroup(f"🛑 Игра остановлена. {reason}"),
                ]
                for p in state.players:
                    effects.append(Unmute(p.user_id))
                state.phase = Phase.ENDED
                state.deadline_ts = None
                await repo.abort_match(session, match_id)
            await self._apply(state, effects)
        self._drop_caches(match_id)

    def _mafia_drop(self, match_id: int) -> None:
        self._mafia_lines.pop(match_id, None)
        for key in [k for k in self._mafia_msgs if k[0] == match_id]:
            self._mafia_msgs.pop(key, None)

    def _drop_caches(self, match_id: int) -> None:
        # _locks/_chat_locks stay: popping a lock while waiters hold it races.
        self._mafia_drop(match_id)

    async def relay_mafia(self, match_id: int, sender_id: int, text: str) -> None:
        async with self.lock(match_id):
            async with session_scope() as session:
                state = await repo.load_state(session, match_id)
            if state is None or state.phase != Phase.NIGHT:
                return
            sender = state.by_user(sender_id)
            if sender is None or not sender.alive or sender.team != Team.MAFIA:
                return
            text = text.strip()
            if not text:
                return
            entry = self._mafia_lines.get(match_id)
            if entry is None or entry[0] != state.day:
                lines: list[str] = []
            else:
                lines = entry[1]
            lines.append(mafia_line(sender, text))
            if len(lines) > 40:
                del lines[:-40]
            self._mafia_lines[match_id] = (state.day, lines)
            body = "\n".join(lines)
            for mate in state.alive():
                if mate.team != Team.MAFIA or not mate.pm_ok:
                    continue
                key = (match_id, mate.user_id)
                msg_id = self._mafia_msgs.get(key)
                if msg_id is not None:
                    try:
                        await self.bot.edit_message_text(
                            body,
                            chat_id=mate.user_id,
                            message_id=msg_id,
                        )
                        continue
                    except TelegramAPIError:
                        pass
                try:
                    msg = await self.bot.send_message(mate.user_id, body)
                    self._mafia_msgs[key] = msg.message_id
                except TelegramAPIError:
                    continue

    async def abort_chat(self, chat_id: int, reason: str) -> None:
        async with session_scope() as session:
            match_id = await repo.active_match_in_chat(session, chat_id)
        if match_id:
            await self.abort(match_id, reason)

    async def force_end(self, match_id: int, winner: str) -> None:
        """Завершить партию с подсчётом рейтинга."""
        async with self.lock(match_id):
            async with session_scope() as session:
                state = await repo.load_state(session, match_id)
                if state is None:
                    return
                effects = engine.admin_force_end(state, winner)
                await repo.save_state(session, state)
            await self._apply(state, effects)
            await self.finalize(state)

    # ---------- effects ----------

    async def _apply(self, state: GameState, effects: list[Effect]) -> None:
        gifs = await self.gifs_for(state.chat_id)
        pm_warn: list[str] = []
        night_pm_failed = False
        dirty = False
        for fx in effects:
            try:
                if isinstance(fx, SendGroup):
                    await self._send_group(state, fx, gifs)
                elif isinstance(fx, EditGroup):
                    await self._edit_group(state, fx)
                elif isinstance(fx, SendPM):
                    sent = await self._send_pm(state, fx, pm_warn)
                    if not sent and fx.role_prompt:
                        night_pm_failed = True
                    dirty = True
                elif isinstance(fx, EditPM):
                    await self._edit_pm(state, fx)
                elif isinstance(fx, Mute):
                    await self._mute(fx.user_id, state.chat_id)
                elif isinstance(fx, Unmute):
                    await self._unmute(fx.user_id, state.chat_id)
            except Exception:
                log.exception("effect failed: %s", type(fx).__name__)
        if pm_warn:
            text = "⚠️ Не удалось написать в ЛС этим игрокам:\n" + "\n".join(pm_warn)
            try:
                await self.bot.send_message(state.chat_id, text)
            except TelegramAPIError:
                pass
        if night_pm_failed:
            # no names: naming night-PM failures would leak roles
            try:
                await self.bot.send_message(
                    state.chat_id,
                    "⚠️ Не удалось написать в ЛС некоторым игрокам — "
                    "они не смогут действовать этой ночью.",
                )
            except TelegramAPIError:
                pass
        if dirty:
            async with session_scope() as session:
                await repo.save_state(session, state)

    async def _send_group(
        self, state: GameState, fx: SendGroup, gifs: dict[str, str]
    ) -> None:
        gif = None
        if fx.tag:
            gif = gifs.get(GIF_TAG_KIND.get(fx.tag, ""))
        if gif:
            msg = await self.bot.send_animation(
                state.chat_id,
                animation=gif,
                caption=fx.text,
                parse_mode="HTML",
                reply_markup=self._kb(fx.kb, state),
            )
            kind = "anim"
        else:
            msg = await self.bot.send_message(
                state.chat_id,
                fx.text,
                parse_mode="HTML",
                reply_markup=self._kb(fx.kb, state),
            )
            kind = "text"
        if fx.tag == "vote":
            async with session_scope() as session:
                match = await repo.get_match(session, state.match_id)
                if match is not None:
                    match.vote_msg_id = msg.message_id
                    match.vote_msg_kind = kind
        elif fx.tag in ("night_banner", "day_banner"):
            async with session_scope() as session:
                match = await repo.get_match(session, state.match_id)
                if match is not None:
                    match.banner_msg_id = msg.message_id
                    match.banner_kind = kind

    async def _edit_group(self, state: GameState, fx: EditGroup) -> None:
        markup = self._kb(fx.kb, state)
        try:
            async with session_scope() as session:
                match = await repo.get_match(session, state.match_id)
                if match is None:
                    return
                is_caption = False
                if match.vote_msg_id == fx.msg_id and match.vote_msg_kind == "anim":
                    is_caption = True
                if match.banner_msg_id == fx.msg_id and match.banner_kind == "anim":
                    is_caption = True
            if is_caption:
                await self.bot.edit_message_caption(
                    caption=fx.text,
                    chat_id=state.chat_id,
                    message_id=fx.msg_id,
                    parse_mode="HTML", reply_markup=markup,
                )
            else:
                await self.bot.edit_message_text(
                    fx.text,
                    chat_id=state.chat_id,
                    message_id=fx.msg_id,
                    parse_mode="HTML", reply_markup=markup,
                )
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise

    async def _send_pm(self, state: GameState, fx: SendPM, warn: list[str]) -> bool:
        player = state.by_user(fx.user_id)
        try:
            msg = await self.bot.send_message(
                fx.user_id, fx.text, parse_mode="HTML",
                reply_markup=self._kb(fx.kb, state),
            )
            if player is not None and fx.role_prompt:
                player.night_msg_id = msg.message_id
            return True
        except TelegramForbiddenError:
            # user blocked the bot or never started it: permanent
            if player is not None:
                player.pm_ok = False
                if not fx.role_prompt:
                    warn.append(
                        f"• {html.escape(player.name)} — не запускал(а) бота в ЛС"
                    )
            return False
        except TelegramAPIError as e:
            # flood/network blip: transient, keep pm_ok for the next night
            log.warning("pm failed user=%s role_prompt=%s: %s", fx.user_id, fx.role_prompt, e)
            if player is not None and not fx.role_prompt:
                warn.append(f"• {html.escape(player.name)} — временная ошибка ЛС")
            return False

    async def _edit_pm(self, state: GameState, fx: EditPM) -> None:
        player = state.by_user(fx.user_id)
        markup = self._kb(fx.kb, state)
        msg_id = player.night_msg_id if player else None
        if msg_id is not None:
            try:
                await self.bot.edit_message_text(
                    fx.text,
                    chat_id=fx.user_id,
                    message_id=msg_id,
                    parse_mode="HTML", reply_markup=markup,
                )
                return
            except TelegramBadRequest:
                pass
            except TelegramAPIError:
                pass
        try:
            msg = await self.bot.send_message(
                fx.user_id, fx.text, parse_mode="HTML", reply_markup=markup
            )
            if player is not None:
                player.night_msg_id = msg.message_id
        except TelegramForbiddenError:
            if player is not None:
                player.pm_ok = False
        except TelegramAPIError as e:
            log.warning("pm edit failed user=%s: %s", fx.user_id, e)

    async def _mute(self, user_id: int, chat_id: int) -> None:
        until = int(time.time()) + 365 * 24 * 3600
        try:
            await self.bot.ban_chat_member(chat_id, user_id, until_date=until)
        except TelegramAPIError as e:
            log.info("mute failed chat=%s user=%s: %s", chat_id, user_id, e)

    async def _unmute(self, user_id: int, chat_id: int) -> None:
        try:
            await self.bot.restrict_chat_member(
                chat_id, user_id, permissions=FULL_PERMS
            )
        except TelegramAPIError as e:
            log.info("unmute failed chat=%s user=%s: %s", chat_id, user_id, e)

    def _kb(self, spec: engine.KBSpec, state: GameState) -> InlineKeyboardMarkup | None:
        if spec is None:
            return None
        kind = spec[0]
        if kind == "vote":
            return kb.vote_kb(state)
        if kind in ("night_mafia", "night_sheriff", "night_doctor"):
            actor_seat = int(spec[2]) if len(spec) > 2 else None
            if kind == "night_mafia":
                return kb.night_kb(state, kind, None)
            return kb.night_kb(state, kind, actor_seat)
        if kind == "hunter":
            return kb.hunter_kb(state)
        if kind == "rematch":
            return kb.rematch_kb(int(spec[1]))
        return None

    # ---------- finalize ----------

    async def finalize(self, state: GameState) -> None:
        winner = state.winner or "town"
        rating_enabled = state.rated
        deltas: dict[int, int] = {}

        async with session_scope() as session:
            stats = await repo.get_stats_many(session, [p.user_id for p in state.players])
            if rating_enabled:
                ratings = {p.user_id: stats[p.user_id].rating for p in state.players}
                teams = {p.user_id: str(p.team or "") for p in state.players}
                deltas = rating.compute_deltas(ratings, teams, winner)

            for p in state.players:
                st = stats[p.user_id]
                won = (
                    (winner == T.WINNER_TOWN and p.team == Team.TOWN)
                    or (winner == T.WINNER_MAFIA and p.team == Team.MAFIA)
                    or (winner == T.WINNER_SOLO and p.team == Team.SOLO)
                )
                st.games += 1
                if won:
                    st.wins += 1
                    st.streak += 1
                    st.best_streak = max(st.best_streak, st.streak)
                else:
                    st.losses += 1
                    st.streak = 0
                if won:
                    if p.team == Team.MAFIA:
                        st.wins_mafia += 1
                    elif p.team == Team.TOWN:
                        st.wins_town += 1
                        if p.alive:
                            st.flawless_wins += 1
                    elif p.team == Team.SOLO:
                        st.wins_clown += 1
                for key, n in state.progress.get(p.user_id, {}).items():
                    if hasattr(st, key):
                        setattr(st, key, getattr(st, key) + n)
                if rating_enabled:
                    st.rating += deltas.get(p.user_id, 0)
                cs = await repo.get_chat_stats(session, p.user_id, state.chat_id)
                cs.games += 1
                if won:
                    cs.wins += 1
                if rating_enabled:
                    cs.rating = max(rating.RATING_FLOOR, cs.rating + deltas.get(p.user_id, 0))
                mp = await session.get(repo.MatchPlayer, (state.match_id, p.seat))
                if mp is not None:
                    mp.rating_delta = deltas.get(p.user_id, 0) if rating_enabled else 0

            new_achs: dict[int, list[str]] = {}
            for p in state.players:
                have = await repo.get_achievements(session, p.user_id)
                unlocked = ach_mod.check(stats[p.user_id], have)
                if unlocked:
                    keys = [a.key for a in unlocked]
                    await repo.add_achievements(session, p.user_id, keys)
                    stats[p.user_id].achievements_count += len(keys)
                    new_achs[p.user_id] = keys

            t_points: dict[int, int] = {}
            if state.tournament_id is not None:
                t = await repo.get_tournament(session, state.tournament_id)
                if t is not None and t.status == "playing":
                    winners = [
                        p for p in state.players
                        if (winner == T.WINNER_TOWN and p.team == Team.TOWN)
                        or (winner == T.WINNER_MAFIA and p.team == Team.MAFIA)
                        or (winner == T.WINNER_SOLO and p.team == Team.SOLO)
                    ]
                    for p in state.players:
                        tp = await session.get(
                            repo.TournamentPlayer, (t.id, p.user_id)
                        )
                        if tp is None:
                            continue
                        if p in winners:
                            tp.points += t.points_win
                            tp.wins += 1
                            t_points[p.user_id] = t.points_win
            await session.commit()

        if rating_enabled and deltas:
            rows = [
                f"{html.escape(p.name)}: {deltas.get(p.user_id, 0):+d}"
                for p in state.players
            ]
            try:
                await self.bot.send_message(
                    state.chat_id,
                    "📊 <b>Рейтинг партии:</b>\n" + "\n".join(rows),
                    parse_mode="HTML",
                )
            except TelegramAPIError:
                pass
        if t_points:
            rows = [
                f"{html.escape(next(p.name for p in state.players if p.user_id == uid))}: +{pts}"
                for uid, pts in t_points.items()
            ]
            try:
                await self.bot.send_message(
                    state.chat_id,
                    "🏆 <b>Очки турнира:</b>\n" + "\n".join(rows),
                    parse_mode="HTML",
                )
            except TelegramAPIError:
                pass
        for uid, keys in new_achs.items():
            for key in keys:
                a = ach_mod.ACH_BY_KEY[key]
                try:
                    await self.bot.send_message(
                        state.chat_id,
                        f"{a.emoji} <b>Достижение!</b> {html.escape(name_of(state, uid))} "
                        f"получает «{a.title}» — {a.desc}",
                        parse_mode="HTML",
                    )
                except TelegramAPIError:
                    pass

        if state.tournament_id is not None:
            await self._tournament_round_done(state)

        self._drop_caches(state.match_id)

    async def _tournament_round_done(self, state: GameState) -> None:
        async with session_scope() as session:
            t = await repo.get_tournament(session, state.tournament_id)  # type: ignore[arg-type]
            if t is None:
                return
            t.round_no += 1
            if t.round_no >= t.games_planned:
                t.status = "finished"
                players = await repo.tournament_players(session, t.id)
                if players:
                    champ = players[0]
                    champ_st = await repo.get_stats(session, champ.user_id)
                    champ_st.tournaments_wins += 1
                    table = "\n".join(
                        f"{i}. {html.escape(p.name)} — {p.points} очк. ({p.wins} побед)"
                        for i, p in enumerate(players, 1)
                    )
                    await session.commit()
                    await self.bot.send_message(
                        state.chat_id,
                        f"🏁 <b>Турнир завершён!</b>\nЧемпион: <b>{html.escape(champ.name)}</b>\n\n"
                        f"Итоговая таблица:\n{table}",
                        parse_mode="HTML",
                    )
                return
            await session.commit()
            next_round = t.round_no + 1
            await self.bot.send_message(
                state.chat_id,
                f"▶️ Раунд {next_round}/{t.games_planned}. Ждём игроков — /mafia",
                parse_mode="HTML",
            )

    # ---------- ticker ----------

    async def tick(self, now: int) -> None:
        async with session_scope() as session:
            rows = await repo.active_match_rows(session)
        for row in rows:
            if row.deadline_ts is not None and row.deadline_ts <= now:
                try:
                    await self.run(row.id, lambda s, n=now: engine.on_deadline(s, n))
                except engine.EngineError as e:
                    log.warning("deadline op failed: %s", e)
                except Exception:
                    log.exception("deadline failed match=%s", row.id)
                continue
            try:
                await self._countdown(row, now)
            except Exception:
                log.exception("countdown failed match=%s", row.id)

    async def _countdown(self, row: Any, now: int) -> None:
        if row.deadline_ts is None:
            return
        if row.phase == Phase.DAY_VOTE.value and row.vote_msg_id and now % 5 == 0:
            async with self.lock(row.id):
                async with session_scope() as session:
                    state = await repo.load_state(session, row.id)
                if state is None or state.deadline_ts is None:
                    return
                text = engine.vote_text(state, now)
                await self._edit_group(
                    state, EditGroup(row.vote_msg_id, text, ("vote", str(row.day)))
                )
        elif row.phase in (Phase.DAY_DISCUSS.value, Phase.NIGHT.value) and row.banner_msg_id:
            if now % 15 != 0:
                return
            remain = max(0, row.deadline_ts - now)
            async with self.lock(row.id):
                async with session_scope() as session:
                    state = await repo.load_state(session, row.id)
                if state is None:
                    return
                if row.phase == Phase.NIGHT.value:
                    text = f"🌙 <b>Ночь {state.day}.</b> Город засыпает… ⏱ {remain} с"
                else:
                    text = (
                        T.day_banner(
                            state.day, state.settings.discuss_s, state.alive_pairs()
                        )
                        + f"\n\n⏱ Осталось: {remain} с"
                    )
                await self._edit_group(state, EditGroup(row.banner_msg_id, text))


def name_of(state: GameState, user_id: int) -> str:
    p = state.by_user(user_id)
    return p.name if p else "?"
