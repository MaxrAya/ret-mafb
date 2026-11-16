from __future__ import annotations

import html
import random
from dataclasses import dataclass, field
from enum import StrEnum

from mafia.game.roles import (
    ROLE_TEAM,
    GameSettings,
    Role,
    RolePoolError,
    Team,
    auto_role_counts,
)
from mafia.ui import texts as T

KBSpec = tuple[str, ...] | None


class Phase(StrEnum):
    NIGHT = "night"
    DAY_DISCUSS = "day_discuss"
    DAY_VOTE = "day_vote"
    HUNTER = "hunter"
    ENDED = "ended"


class Effect:
    pass


@dataclass
class SendGroup(Effect):
    text: str
    kb: KBSpec = None
    tag: str | None = None


@dataclass
class EditGroup(Effect):
    msg_id: int
    text: str
    kb: KBSpec = None


@dataclass
class SendPM(Effect):
    user_id: int
    text: str
    kb: KBSpec = None
    role_prompt: bool = False


@dataclass
class EditPM(Effect):
    user_id: int
    seat: int
    text: str
    kb: KBSpec = None


@dataclass
class Mute(Effect):
    user_id: int


@dataclass
class Unmute(Effect):
    user_id: int


@dataclass
class GPlayer:
    user_id: int
    seat: int
    name: str
    role: Role | None = None
    team: Team | None = None
    alive: bool = True
    died_day: int | None = None
    death_reason: str | None = None
    pm_ok: bool = True
    night_msg_id: int | None = None
    self_heal_used: bool = False


@dataclass
class GameState:
    match_id: int
    chat_id: int
    host_id: int
    settings: GameSettings
    phase: Phase = Phase.NIGHT
    day: int = 1
    deadline_ts: int | None = None
    players: list[GPlayer] = field(default_factory=list)
    votes: dict[int, int] = field(default_factory=dict)
    night: dict[int, int] = field(default_factory=dict)
    winner: str | None = None
    rated: bool = True
    tournament_id: int | None = None
    resume_phase: Phase | None = None
    pending_hunter_seat: int | None = None
    clown_win: bool = False
    progress: dict[int, dict[str, int]] = field(default_factory=dict)

    def alive(self) -> list[GPlayer]:
        return [p for p in self.players if p.alive]

    def by_seat(self, seat: int) -> GPlayer | None:
        for p in self.players:
            if p.seat == seat:
                return p
        return None

    def by_user(self, user_id: int) -> GPlayer | None:
        for p in self.players:
            if p.user_id == user_id:
                return p
        return None

    def alive_pairs(self) -> list[tuple[int, str]]:
        return [(p.seat, p.name) for p in self.alive()]


def bump(state: GameState, user_id: int, key: str, n: int = 1) -> None:
    slot = state.progress.setdefault(user_id, {})
    slot[key] = slot.get(key, 0) + n


class EngineError(Exception):
    def __init__(self, msg: str, alert: bool = True) -> None:
        super().__init__(msg)
        self.alert = alert


def mafia_allies(state: GameState, me: GPlayer) -> list[str]:
    return [
        p.name
        for p in state.players
        if p.alive and p.team == Team.MAFIA and p.seat != me.seat
    ]


def _mafia_tally_lines(state: GameState) -> list[str]:
    names = {p.seat: p.name for p in state.players}
    rows: list[str] = []
    for seat, target in sorted(state.night.items()):
        actor = state.by_seat(seat)
        if not actor or not actor.alive or actor.team != Team.MAFIA:
            continue
        rows.append(f"• {actor.name} → {names.get(target, '?')}")
    return rows


def night_prompt_for(state: GameState, p: GPlayer) -> tuple[str, KBSpec] | None:
    if not p.alive or p.role is None:
        return None
    day = state.day
    if p.role in (Role.MAFIA, Role.DON, Role.GODFATHER):
        return (
            T.night_prompt_mafia(
                day, p.role, mafia_allies(state, p), _mafia_tally_lines(state)
            ),
            ("night_mafia", day),
        )
    if p.role == Role.SHERIFF:
        return T.night_prompt_sheriff(day), ("night_sheriff", day, str(p.seat))
    if p.role == Role.DOCTOR:
        return T.night_prompt_doctor(day), ("night_doctor", day, str(p.seat))
    return T.night_prompt_sleep(day, p.role), None


def _night_prompts(state: GameState, now_ts: int) -> list[Effect]:
    state.phase = Phase.NIGHT
    state.deadline_ts = now_ts + state.settings.night_s
    effects: list[Effect] = [SendGroup(T.night_banner(state.day), tag="night_banner")]
    warns: list[str] = []
    for p in state.alive():
        effects.append(Mute(p.user_id))
        prompt = night_prompt_for(state, p)
        if prompt is None:
            continue
        text, kb = prompt
        if not p.pm_ok:
            warns.append(f"• {html.escape(p.name)} — нет доступа в ЛС")
            continue
        effects.append(SendPM(p.user_id, text, kb, role_prompt=True))
    if warns:
        effects.append(
            SendGroup(
                "⚠️ Эти игроки не смогут действовать ночью:\n"
                + "\n".join(warns)
            )
        )
    return effects


def new_game(
    match_id: int,
    chat_id: int,
    host_id: int,
    raw_players: list[tuple[int, str]],
    settings: GameSettings,
    rated: bool,
    tournament_id: int | None,
    now_ts: int,
    rng: random.Random | None = None,
) -> tuple[GameState, list[Effect]]:
    rng = rng or random.Random()
    n = len(raw_players)
    counts = auto_role_counts(n, settings)

    bag: list[Role] = []
    for role, cnt in counts.items():
        bag.extend([role] * cnt)
    rng.shuffle(bag)
    shuffled = list(raw_players)
    rng.shuffle(shuffled)

    players: list[GPlayer] = []
    for i, ((user_id, name), role) in enumerate(zip(shuffled, bag, strict=True), start=1):
        players.append(
            GPlayer(user_id=user_id, seat=i, name=name, role=role, team=ROLE_TEAM[role])
        )

    state = GameState(
        match_id=match_id,
        chat_id=chat_id,
        host_id=host_id,
        settings=settings,
        phase=Phase.NIGHT,
        day=1,
        players=players,
        rated=rated,
        tournament_id=tournament_id,
    )

    effects: list[Effect] = [SendGroup(T.game_start(n), tag="start")]
    for p in players:
        assert p.role is not None
        teammates: list[str] = []
        if p.team == Team.MAFIA:
            teammates = [
                q.name for q in players if q.team == Team.MAFIA and q.seat != p.seat
            ]
        if not p.pm_ok:
            continue
        effects.append(SendPM(p.user_id, T.role_pm(p.role, teammates, 1), None))
    effects.extend(_night_prompts(state, now_ts))
    return state, effects


def night_pick(
    state: GameState, actor_seat: int, target_seat: int, now_ts: int
) -> list[Effect]:
    if state.phase != Phase.NIGHT:
        raise EngineError("Сейчас не ночь")
    actor = state.by_seat(actor_seat)
    target = state.by_seat(target_seat)
    if actor is None or not actor.alive or actor.role is None:
        raise EngineError("Действие недоступно")
    if target is None or not target.alive:
        raise EngineError("Цель недоступна")

    role = actor.role
    if role in (Role.MAFIA, Role.DON, Role.GODFATHER):
        if target.team == Team.MAFIA:
            raise EngineError("Нельзя атаковать своих")
    elif role == Role.SHERIFF:
        if target.seat == actor.seat:
            raise EngineError("Нельзя проверить себя")
    elif role == Role.DOCTOR:
        if target.seat == actor.seat and actor.self_heal_used:
            raise EngineError("Себя можно спасти только один раз за игру")
    else:
        raise EngineError("У вас нет ночного действия")

    state.night[actor_seat] = target_seat

    effects: list[Effect] = []
    if role in (Role.MAFIA, Role.DON, Role.GODFATHER):
        for mate in state.alive():
            if mate.team != Team.MAFIA:
                continue
            text_mafia, kb = night_prompt_for(state, mate)
            effects.append(EditPM(mate.user_id, mate.seat, text_mafia, kb))
    return effects


def _tally(state: GameState) -> tuple[dict[int, int], dict[int, int]]:
    tally: dict[int, int] = {}
    for target in state.votes.values():
        tally[target] = tally.get(target, 0) + 1
    return tally, dict(state.votes)


def vote_text(state: GameState, now_ts: int) -> str:
    remain = max(0, (state.deadline_ts or now_ts) - now_ts)
    tally, votes_from = _tally(state)
    return T.vote_tally_text(
        state.day,
        f"осталось {remain} с",
        state.alive_pairs(),
        tally,
        votes_from,
        state.settings.anonymous_vote,
    )


def cast_vote(state: GameState, voter_seat: int, target_seat: int) -> None:
    if state.phase != Phase.DAY_VOTE:
        raise EngineError("Голосование ещё не началось")
    voter = state.by_seat(voter_seat)
    target = state.by_seat(target_seat)
    if voter is None or not voter.alive:
        raise EngineError("Вы мертвы")
    if target is None or not target.alive:
        raise EngineError("Цель недоступна")
    if target.seat == voter.seat:
        raise EngineError("За себя голосовать нельзя")
    state.votes[voter_seat] = target_seat


def open_day(state: GameState, now_ts: int) -> list[Effect]:
    state.phase = Phase.DAY_DISCUSS
    state.deadline_ts = now_ts + state.settings.discuss_s
    state.votes.clear()
    effects: list[Effect] = [
        SendGroup(
            T.day_banner(state.day, state.settings.discuss_s, state.alive_pairs()),
            tag="day_banner",
        )
    ]
    for p in state.alive():
        effects.append(Unmute(p.user_id))
    return effects


def open_vote(state: GameState, now_ts: int) -> list[Effect]:
    state.phase = Phase.DAY_VOTE
    state.deadline_ts = now_ts + state.settings.vote_s
    return [
        SendGroup(
            T.vote_open(state.day, state.settings.vote_s, state.alive_pairs()),
            kb=("vote", state.day),
            tag="vote",
        )
    ]


def _check_winner(state: GameState) -> str | None:
    if state.clown_win:
        return T.WINNER_SOLO
    mafia = [p for p in state.alive() if p.team == Team.MAFIA]
    others = [p for p in state.alive() if p.team != Team.MAFIA]
    if not mafia:
        return T.WINNER_TOWN
    if len(mafia) >= len(others):
        return T.WINNER_MAFIA
    return None


def _apply_death(
    state: GameState, victim: GPlayer, reason: str
) -> tuple[list[Effect], bool]:
    effects: list[Effect] = []
    victim.alive = False
    victim.died_day = state.day
    victim.death_reason = reason

    clown_win = False
    if victim.role == Role.CLOWN and reason in ("lynch", "night"):
        clown_win = True
        state.clown_win = True

    if victim.role == Role.HUNTER:
        state.pending_hunter_seat = victim.seat

    effects.append(Mute(victim.user_id))
    return effects, clown_win


def _end(state: GameState, winner: str) -> list[Effect]:
    state.winner = winner
    state.phase = Phase.ENDED
    state.deadline_ts = None
    reveal = [(p.name, str(p.role or ""), p.alive) for p in state.players]
    effects: list[Effect] = [SendGroup(T.end_message(winner, reveal), tag="end")]
    for p in state.players:
        effects.append(Unmute(p.user_id))
    return effects


def admin_force_end(state: GameState, winner: str) -> list[Effect]:
    """Завершение партии по команде администратора."""
    return _end(state, winner)


def current_winner(state: GameState) -> str | None:
    """Победитель по текущему составу живых, если он уже определился."""
    return _check_winner(state)


def resolve_vote(state: GameState, now_ts: int) -> list[Effect]:
    if state.phase != Phase.DAY_VOTE:
        raise EngineError("Нет активного голосования")
    alive = state.alive()
    alive_n = len(alive)
    tally, _ = _tally(state)
    majority = alive_n // 2 + 1
    top = 0
    top_seats = [s for s, c in tally.items() if c == max(tally.values())] if tally else []
    if len(top_seats) == 1:
        top = tally[top_seats[0]]

    effects: list[Effect] = []
    lynched: GPlayer | None = None
    if top_seats and len(top_seats) == 1 and top >= majority:
        lynched = state.by_seat(top_seats[0])
        assert lynched is not None
        for voter_seat in state.votes:
            if state.votes[voter_seat] == lynched.seat:
                voter = state.by_seat(voter_seat)
                if voter is not None:
                    bump(state, voter.user_id, "good_votes")
        effects.append(SendGroup(T.lynch_result(lynched.name, lynched.role or Role.CITIZEN)))
        death_fx, clown = _apply_death(state, lynched, "lynch")
        effects.extend(death_fx)
    else:
        best = max(tally.values()) if tally else 0
        effects.append(SendGroup(T.lynch_none(state.day, best, alive_n)))

    if state.clown_win:
        effects.extend(_end(state, T.WINNER_SOLO))
        return effects

    if state.pending_hunter_seat is not None:
        shooter = state.by_seat(state.pending_hunter_seat)
        state.resume_phase = Phase.NIGHT
        state.phase = Phase.HUNTER
        state.deadline_ts = now_ts + state.settings.hunter_s
        effects.append(SendGroup(T.hunter_group_prompt(shooter.name if shooter else "?")))
        if shooter is not None and shooter.pm_ok:
            effects.append(
                SendPM(
                    shooter.user_id,
                    T.hunter_prompt(state.day, shooter.name),
                    ("hunter", state.day),
                )
            )
        return effects

    winner = _check_winner(state)
    if winner:
        effects.extend(_end(state, winner))
        return effects

    effects.extend(_open_night(state, now_ts))
    return effects


def _open_night(state: GameState, now_ts: int) -> list[Effect]:
    state.day += 1
    state.night.clear()
    state.votes.clear()
    return _night_prompts(state, now_ts)


def resolve_night(state: GameState, now_ts: int) -> list[Effect]:
    if state.phase != Phase.NIGHT:
        raise EngineError("Сейчас не ночь")
    effects: list[Effect] = []

    doctor: GPlayer | None = None
    sheriff: GPlayer | None = None
    kill_votes: dict[int, int] = {}
    kill_voters: dict[int, list[GPlayer]] = {}

    for seat, target in list(state.night.items()):
        actor = state.by_seat(seat)
        tgt = state.by_seat(target)
        if actor is None or not actor.alive or actor.role is None or tgt is None:
            continue
        if actor.role == Role.DOCTOR:
            doctor = actor
            doctor_target = tgt
            if tgt.seat == actor.seat:
                actor.self_heal_used = True
        elif actor.role == Role.SHERIFF:
            sheriff = actor
            sheriff_target = tgt
        elif actor.team == Team.MAFIA:
            weight = 2 if actor.role == Role.DON else 1
            kill_votes[target] = kill_votes.get(target, 0) + weight
            kill_voters.setdefault(target, []).append(actor)

    victim: GPlayer | None = None
    if kill_votes:
        best = max(kill_votes.values())
        leaders = [s for s, c in kill_votes.items() if c == best]
        if len(leaders) == 1:
            victim = state.by_seat(leaders[0])

    godfather_alive = any(
        p.alive and p.role == Role.GODFATHER for p in state.players
    )
    saved = (
        victim is not None
        and doctor is not None
        and doctor_target.seat == victim.seat
        and not godfather_alive
    )

    if sheriff is not None:
        tgt = sheriff_target
        is_mafia = tgt.team == Team.MAFIA
        bump(state, sheriff.user_id, "checks")
        if sheriff.pm_ok:
            effects.append(SendPM(sheriff.user_id, T.sheriff_result(tgt.name, is_mafia)))

    if victim is None:
        effects.append(SendGroup(T.morning_quiet(state.day)))
    elif saved:
        effects.append(SendGroup(T.morning_saved(state.day)))
    else:
        for voter in kill_voters.get(victim.seat, []):
            bump(state, voter.user_id, "night_kills")
        effects.append(
            SendGroup(T.morning_body(state.day, victim.name, victim.role or Role.CITIZEN))
        )
        death_fx, _ = _apply_death(state, victim, "night")
        effects.extend(death_fx)

    if state.clown_win:
        effects.extend(_end(state, T.WINNER_SOLO))
        return effects

    if state.pending_hunter_seat is not None:
        shooter = state.by_seat(state.pending_hunter_seat)
        state.resume_phase = Phase.DAY_DISCUSS
        state.phase = Phase.HUNTER
        state.deadline_ts = now_ts + state.settings.hunter_s
        effects.append(SendGroup(T.hunter_group_prompt(shooter.name if shooter else "?")))
        if shooter is not None and shooter.pm_ok:
            effects.append(
                SendPM(
                    shooter.user_id,
                    T.hunter_prompt(state.day, shooter.name),
                    ("hunter", state.day),
                )
            )
        return effects

    winner = _check_winner(state)
    if winner:
        effects.extend(_end(state, winner))
        return effects

    effects.extend(open_day(state, now_ts))
    return effects


def resolve_hunter(
    state: GameState, target_seat: int | None, now_ts: int
) -> list[Effect]:
    if state.phase != Phase.HUNTER or state.pending_hunter_seat is None:
        raise EngineError("Охотник сейчас не стреляет")
    shooter = state.by_seat(state.pending_hunter_seat)
    effects: list[Effect] = []
    resume = state.resume_phase or Phase.NIGHT

    if target_seat is not None:
        target = state.by_seat(target_seat)
        if target is None or not target.alive:
            raise EngineError("Цель недоступна")
        if shooter is not None:
            bump(state, shooter.user_id, "hunter_shots")
            effects.append(
                SendGroup(
                    T.hunter_shot(shooter.name, target.name, target.role or Role.CITIZEN)
                )
            )
        state.pending_hunter_seat = None
        death_fx, _ = _apply_death(state, target, "hunter")
        effects.extend(death_fx)
        chained = state.pending_hunter_seat
    else:
        state.pending_hunter_seat = None
        effects.append(SendGroup(T.hunter_no_shot(shooter.name if shooter else "?")))
        chained = None

    state.resume_phase = None

    if state.clown_win:
        effects.extend(_end(state, T.WINNER_SOLO))
        return effects

    if chained is not None:
        # chained hunter (target was hunter) — fire again
        chain = state.by_seat(chained)
        state.pending_hunter_seat = chained
        state.resume_phase = resume
        state.phase = Phase.HUNTER
        state.deadline_ts = now_ts + state.settings.hunter_s
        effects.append(SendGroup(T.hunter_group_prompt(chain.name if chain else "?")))
        if chain is not None and chain.pm_ok:
            effects.append(
                SendPM(
                    chain.user_id,
                    T.hunter_prompt(state.day, chain.name),
                    ("hunter", state.day),
                )
            )
        return effects

    winner = _check_winner(state)
    if winner:
        effects.extend(_end(state, winner))
        return effects

    if resume == Phase.DAY_DISCUSS:
        effects.extend(open_day(state, now_ts))
    else:
        effects.extend(_open_night(state, now_ts))
    return effects


def host_skip(state: GameState, now_ts: int) -> list[Effect]:
    if state.phase == Phase.DAY_DISCUSS:
        return open_vote(state, now_ts)
    if state.phase == Phase.DAY_VOTE:
        return resolve_vote(state, now_ts)
    if state.phase == Phase.NIGHT:
        return resolve_night(state, now_ts)
    if state.phase == Phase.HUNTER:
        return resolve_hunter(state, None, now_ts)
    raise EngineError("Игра уже закончена")


def on_deadline(state: GameState, now_ts: int) -> list[Effect]:
    if state.phase == Phase.DAY_DISCUSS:
        return open_vote(state, now_ts)
    if state.phase == Phase.DAY_VOTE:
        return resolve_vote(state, now_ts)
    if state.phase == Phase.NIGHT:
        return resolve_night(state, now_ts)
    if state.phase == Phase.HUNTER:
        return resolve_hunter(state, None, now_ts)
    return []


__all__ = [
    "Effect",
    "EngineError",
    "GPlayer",
    "GameState",
    "Mute",
    "EditGroup",
    "EditPM",
    "Phase",
    "SendGroup",
    "SendPM",
    "Unmute",
    "bump",
    "cast_vote",
    "host_skip",
    "new_game",
    "night_pick",
    "night_prompt_for",
    "on_deadline",
    "open_day",
    "open_vote",
    "resolve_hunter",
    "resolve_night",
    "resolve_vote",
    "RolePoolError",
]
