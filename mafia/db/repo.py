from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mafia.db.models import (
    Achievement,
    ChatGif,
    ChatStats,
    Lobby,
    LobbyPlayer,
    Match,
    MatchPlayer,
    NightAction,
    PlayerStats,
    Subscription,
    Tournament,
    TournamentPlayer,
    User,
    Vote,
)
from mafia.game.engine import GameState, GPlayer, Phase
from mafia.game.roles import GameSettings


def utcnow() -> datetime:
    return datetime.now(UTC)


# ---------- users & stats ----------


async def ensure_user(session: AsyncSession, user_id: int, name: str, username: str | None) -> None:
    row = await session.get(User, user_id)
    if row is None:
        session.add(User(id=user_id, username=username, full_name=name))
    else:
        row.full_name = name
        row.username = username


async def get_stats(session: AsyncSession, user_id: int) -> PlayerStats:
    row = await session.get(PlayerStats, user_id)
    if row is None:
        row = PlayerStats(user_id=user_id)
        session.add(row)
        await session.flush()
    return row


async def get_stats_many(session: AsyncSession, user_ids: list[int]) -> dict[int, PlayerStats]:
    out: dict[int, PlayerStats] = {}
    for uid in user_ids:
        out[uid] = await get_stats(session, uid)
    return out


async def get_chat_stats(session: AsyncSession, user_id: int, chat_id: int) -> ChatStats:
    row = await session.get(ChatStats, (user_id, chat_id))
    if row is None:
        row = ChatStats(user_id=user_id, chat_id=chat_id)
        session.add(row)
        await session.flush()
    return row


async def get_achievements(session: AsyncSession, user_id: int) -> set[str]:
    rows = (
        await session.execute(select(Achievement.key).where(Achievement.user_id == user_id))
    ).scalars()
    return set(rows)


async def add_achievements(session: AsyncSession, user_id: int, keys: list[str]) -> None:
    for key in keys:
        session.add(Achievement(user_id=user_id, key=key))


# ---------- lobby ----------


async def get_lobby(session: AsyncSession, chat_id: int) -> Lobby | None:
    return await session.get(Lobby, chat_id)


async def create_lobby(
    session: AsyncSession, chat_id: int, host_id: int, settings: GameSettings,
    tournament_id: int | None = None,
) -> Lobby:
    row = Lobby(
        chat_id=chat_id,
        host_id=host_id,
        settings_json=settings.to_json(),
        tournament_id=tournament_id,
    )
    session.add(row)
    await session.flush()
    return row


async def delete_lobby(session: AsyncSession, chat_id: int) -> None:
    await session.execute(delete(LobbyPlayer).where(LobbyPlayer.chat_id == chat_id))
    await session.execute(delete(Lobby).where(Lobby.chat_id == chat_id))


async def lobby_players(session: AsyncSession, chat_id: int) -> list[LobbyPlayer]:
    rows = (
        await session.execute(
            select(LobbyPlayer).where(LobbyPlayer.chat_id == chat_id)
            .order_by(LobbyPlayer.joined_at)
        )
    ).scalars()
    return list(rows)


async def lobby_add(session: AsyncSession, chat_id: int, user_id: int, name: str) -> None:
    existing = await session.get(LobbyPlayer, (chat_id, user_id))
    if existing is None:
        session.add(LobbyPlayer(chat_id=chat_id, user_id=user_id, name=name))
    else:
        existing.name = name


async def lobby_remove(session: AsyncSession, chat_id: int, user_id: int) -> None:
    await session.execute(
        delete(LobbyPlayer).where(
            LobbyPlayer.chat_id == chat_id, LobbyPlayer.user_id == user_id
        )
    )


async def user_in_any_lobby(session: AsyncSession, user_id: int) -> int | None:
    rows = (
        await session.execute(select(LobbyPlayer.chat_id).where(LobbyPlayer.user_id == user_id))
    ).scalars()
    first = list(rows)
    return first[0] if first else None


# ---------- matches ----------


async def create_match(
    session: AsyncSession,
    chat_id: int,
    host_id: int,
    settings: GameSettings,
    rated: bool,
    tournament_id: int | None,
) -> Match:
    row = Match(
        chat_id=chat_id,
        host_id=host_id,
        status="active",
        settings_json=settings.to_json(),
        rated=1 if rated else 0,
        tournament_id=tournament_id,
        started_at=utcnow(),
    )
    session.add(row)
    await session.flush()
    return row


async def save_state(session: AsyncSession, state: GameState) -> None:
    match = await session.get(Match, state.match_id)
    if match is None:
        raise RuntimeError(f"match {state.match_id} missing")
    match.phase = state.phase.value
    match.day = state.day
    match.deadline_ts = state.deadline_ts
    match.winner = state.winner
    match.settings_json = state.settings.to_json()
    match.rated = 1 if state.rated else 0
    match.resume_phase = state.resume_phase.value if state.resume_phase else None
    match.clown_win = 1 if state.clown_win else 0
    match.pending_hunter_seat = state.pending_hunter_seat
    match.progress_json = json.dumps(state.progress)
    if state.phase == Phase.ENDED:
        match.status = "finished"
        match.ended_at = utcnow()

    for p in state.players:
        row = await session.get(MatchPlayer, (state.match_id, p.seat))
        if row is None:
            row = MatchPlayer(match_id=state.match_id, seat=p.seat, user_id=p.user_id)
            session.add(row)
        row.name = p.name
        row.role = str(p.role or "")
        row.team = str(p.team or "")
        row.alive = 1 if p.alive else 0
        row.died_day = p.died_day
        row.death_reason = p.death_reason
        row.pm_ok = 1 if p.pm_ok else 0
        row.night_msg_id = p.night_msg_id
        row.self_heal_used = 1 if p.self_heal_used else 0

    await session.execute(
        delete(Vote).where(Vote.match_id == state.match_id, Vote.day <= state.day)
    )
    for voter, target in state.votes.items():
        session.add(
            Vote(match_id=state.match_id, day=state.day, voter_seat=voter, target_seat=target)
        )

    await session.execute(
        delete(NightAction).where(
            NightAction.match_id == state.match_id, NightAction.day <= state.day
        )
    )
    for actor, target in state.night.items():
        role = state.by_seat(actor)
        session.add(
            NightAction(
                match_id=state.match_id,
                day=state.day,
                actor_seat=actor,
                role=str(role.role if role else ""),
                target_seat=target,
            )
        )


async def load_state(session: AsyncSession, match_id: int) -> GameState | None:
    match = await session.get(Match, match_id)
    if match is None or match.status != "active":
        return None
    mp_rows = (
        await session.execute(
            select(MatchPlayer)
            .where(MatchPlayer.match_id == match_id)
            .order_by(MatchPlayer.seat)
        )
    ).scalars()
    players = [
        GPlayer(
            user_id=r.user_id,
            seat=r.seat,
            name=r.name,
            role=r.role or None,
            team=r.team or None,
            alive=bool(r.alive),
            died_day=r.died_day,
            death_reason=r.death_reason,
            pm_ok=bool(r.pm_ok),
            night_msg_id=r.night_msg_id,
            self_heal_used=bool(r.self_heal_used),
        )
        for r in mp_rows
    ]
    from mafia.game.roles import Role, Team  # local to avoid cycle at import

    for p in players:
        if p.role:
            p.role = Role(p.role)
        if p.team:
            p.team = Team(p.team)

    state = GameState(
        match_id=match.id,
        chat_id=match.chat_id,
        host_id=match.host_id,
        settings=GameSettings.from_json(match.settings_json),
        phase=Phase(match.phase),
        day=match.day,
        deadline_ts=match.deadline_ts,
        players=players,
        winner=match.winner,
        rated=bool(match.rated),
        tournament_id=match.tournament_id,
        resume_phase=Phase(match.resume_phase) if match.resume_phase else None,
        clown_win=bool(match.clown_win),
        pending_hunter_seat=match.pending_hunter_seat,
    )
    try:
        raw_progress = json.loads(match.progress_json or "{}")
    except ValueError:
        raw_progress = {}
    state.progress = {int(k): dict(v) for k, v in raw_progress.items()}

    vote_rows = (
        await session.execute(select(Vote).where(Vote.match_id == match_id, Vote.day == state.day))
    ).scalars()
    state.votes = {r.voter_seat: r.target_seat for r in vote_rows}

    night_rows = (
        await session.execute(
            select(NightAction).where(
                NightAction.match_id == match_id, NightAction.day == state.day
            )
        )
    ).scalars()
    state.night = {r.actor_seat: r.target_seat for r in night_rows}
    return state


async def active_match_ids(session: AsyncSession) -> list[int]:
    rows = (
        await session.execute(select(Match.id).where(Match.status == "active"))
    ).scalars()
    return list(rows)


async def active_match_rows(session: AsyncSession) -> list[Match]:
    rows = (
        await session.execute(select(Match).where(Match.status == "active"))
    ).scalars()
    return list(rows)


async def get_match(session: AsyncSession, match_id: int) -> Match | None:
    return await session.get(Match, match_id)


async def active_match_in_chat(session: AsyncSession, chat_id: int) -> int | None:
    rows = (
        await session.execute(
            select(Match.id).where(Match.chat_id == chat_id, Match.status == "active")
        )
    ).scalars()
    first = list(rows)
    return first[0] if first else None


async def user_in_active_match(session: AsyncSession, user_id: int) -> int | None:
    rows = (
        await session.execute(
            select(MatchPlayer.match_id)
            .join(Match, Match.id == MatchPlayer.match_id)
            .where(MatchPlayer.user_id == user_id, Match.status == "active")
            .limit(1)
        )
    ).scalars()
    first = list(rows)
    return first[0] if first else None


async def match_players(session: AsyncSession, match_id: int) -> list[MatchPlayer]:
    rows = (
        await session.execute(
            select(MatchPlayer)
            .where(MatchPlayer.match_id == match_id)
            .order_by(MatchPlayer.seat)
        )
    ).scalars()
    return list(rows)


async def abort_match(session: AsyncSession, match_id: int) -> None:
    match = await session.get(Match, match_id)
    if match is None:
        return
    match.status = "aborted"
    match.phase = Phase.ENDED.value
    match.deadline_ts = None
    match.ended_at = utcnow()


# ---------- recent matches ----------


async def recent_matches(session: AsyncSession, chat_id: int, limit: int = 5) -> list[Match]:
    rows = (
        await session.execute(
            select(Match)
            .where(Match.chat_id == chat_id, Match.status == "finished")
            .order_by(Match.id.desc())
            .limit(limit)
        )
    ).scalars()
    return list(rows)


# ---------- tournaments ----------


async def get_tournament(session: AsyncSession, t_id: int) -> Tournament | None:
    return await session.get(Tournament, t_id)


async def active_tournament(session: AsyncSession, chat_id: int) -> Tournament | None:
    rows = (
        await session.execute(
            select(Tournament)
            .where(Tournament.chat_id == chat_id, Tournament.status.in_(["lobby", "playing"]))
            .order_by(Tournament.id.desc())
            .limit(1)
        )
    ).scalars()
    first = list(rows)
    return first[0] if first else None


async def create_tournament(
    session: AsyncSession, chat_id: int, host_id: int, games: int, points_win: int
) -> Tournament:
    row = Tournament(
        chat_id=chat_id, host_id=host_id, games_planned=games, points_win=points_win
    )
    session.add(row)
    await session.flush()
    return row


async def tournament_players(session: AsyncSession, t_id: int) -> list[TournamentPlayer]:
    rows = (
        await session.execute(
            select(TournamentPlayer)
            .where(TournamentPlayer.tournament_id == t_id)
            .order_by(TournamentPlayer.points.desc(), TournamentPlayer.wins.desc())
        )
    ).scalars()
    return list(rows)


async def tplayer_add(session: AsyncSession, t_id: int, user_id: int, name: str) -> None:
    row = await session.get(TournamentPlayer, (t_id, user_id))
    if row is None:
        session.add(TournamentPlayer(tournament_id=t_id, user_id=user_id, name=name))


async def tplayer_remove(session: AsyncSession, t_id: int, user_id: int) -> None:
    await session.execute(
        delete(TournamentPlayer).where(
            TournamentPlayer.tournament_id == t_id, TournamentPlayer.user_id == user_id
        )
    )


# ---------- gifs & cooldowns ----------


async def get_gifs(session: AsyncSession, chat_id: int) -> dict[str, str]:
    rows = (
        await session.execute(select(ChatGif).where(ChatGif.chat_id == chat_id))
    ).scalars()
    return {r.kind: r.file_id for r in rows}


async def set_gif(session: AsyncSession, chat_id: int, kind: str, file_id: str) -> None:
    row = await session.get(ChatGif, (chat_id, kind))
    if row is None:
        session.add(ChatGif(chat_id=chat_id, kind=kind, file_id=file_id))
    else:
        row.file_id = file_id


# ---------- subscriptions ----------


async def add_sub(session: AsyncSession, user_id: int) -> None:
    row = await session.get(Subscription, user_id)
    if row is None:
        session.add(Subscription(user_id=user_id))


async def del_sub(session: AsyncSession, user_id: int) -> None:
    await session.execute(delete(Subscription).where(Subscription.user_id == user_id))


async def all_subs(session: AsyncSession) -> list[int]:
    rows = (await session.execute(select(Subscription.user_id))).scalars()
    return list(rows)


async def is_sub(session: AsyncSession, user_id: int) -> bool:
    row = await session.get(Subscription, user_id)
    return row is not None


# ---------- period top ----------


async def top_period(
    session: AsyncSession, since: datetime | None, limit: int = 10
) -> list[tuple[int, int, int]]:
    """[(user_id, rating_delta_sum, games)] за период, только рейтинговые партии."""
    stmt = (
        select(
            MatchPlayer.user_id,
            func.sum(MatchPlayer.rating_delta),
            func.count(),
        )
        .join(Match, Match.id == MatchPlayer.match_id)
        .where(Match.status == "finished", Match.rated == 1)
    )
    if since is not None:
        stmt = stmt.where(Match.ended_at >= since)
    stmt = (
        stmt.group_by(MatchPlayer.user_id)
        .order_by(func.sum(MatchPlayer.rating_delta).desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [(r[0], int(r[1] or 0), int(r[2])) for r in rows]
