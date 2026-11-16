from __future__ import annotations

import random

import pytest

from mafia.game import engine as E
from mafia.game.engine import (
    EngineError,
    Mute,
    Phase,
    SendGroup,
    SendPM,
    cast_vote,
    host_skip,
    new_game,
    night_pick,
    on_deadline,
    resolve_hunter,
    resolve_night,
    resolve_vote,
)
from mafia.game.roles import ROLE_TEAM, GameSettings, Role


def make_state(roles: list[Role], settings: GameSettings | None = None) -> E.GameState:
    players = [
        E.GPlayer(
            user_id=100 + i,
            seat=i + 1,
            name=f"P{i + 1}",
            role=r,
            team=ROLE_TEAM[r],
        )
        for i, r in enumerate(roles)
    ]
    return E.GameState(
        match_id=1,
        chat_id=-100,
        host_id=1,
        settings=settings or GameSettings(),
        players=players,
    )


def alive_seat_by_role(state: E.GameState, role: Role) -> int:
    for p in state.players:
        if p.role == role and p.alive:
            return p.seat
    raise AssertionError(f"no alive {role}")


# ---------------------------------------------------------------- new_game


def test_new_game_roles_and_prompts():
    raw = [(100 + i, f"P{i}") for i in range(6)]
    state, effects = new_game(
        1, -100, 1, raw, GameSettings(), True, None, now_ts=0,
        rng=random.Random(42),
    )
    assert state.phase == Phase.NIGHT
    assert len(state.players) == 6
    assert sum(1 for p in state.players if p.team.value == "mafia") == 1
    assert any(isinstance(e, SendPM) for e in effects)
    assert any(isinstance(e, Mute) for e in effects)  # night mutes
    assert any(getattr(e, "tag", None) == "night_banner" for e in effects)
    assert state.deadline_ts == 60


# ---------------------------------------------------------------- night_pick


def test_sheriff_cannot_check_self():
    st = make_state([Role.SHERIFF, Role.CITIZEN, Role.CITIZEN, Role.MAFIA, Role.CITIZEN])
    with pytest.raises(EngineError):
        night_pick(st, 1, 1, 0)


def test_mafia_cannot_kill_own():
    st = make_state([Role.MAFIA, Role.DON, Role.CITIZEN, Role.CITIZEN, Role.CITIZEN])
    with pytest.raises(EngineError):
        night_pick(st, 1, 2, 0)


def test_doctor_self_heal_once():
    st = make_state(
        [Role.DOCTOR, Role.CITIZEN, Role.CITIZEN, Role.MAFIA, Role.CITIZEN]
    )
    night_pick(st, 1, 1, 0)
    resolve_night(st, 100)  # self_heal_used = True
    st.phase = Phase.NIGHT
    with pytest.raises(EngineError, match="один раз"):
        night_pick(st, 1, 1, 200)


def test_dead_cannot_act():
    st = make_state([Role.SHERIFF, Role.CITIZEN, Role.CITIZEN, Role.MAFIA, Role.CITIZEN])
    st.by_seat(1).alive = False
    with pytest.raises(EngineError):
        night_pick(st, 1, 2, 0)


def test_mafia_pick_edits_mates_prompts():
    st = make_state([Role.MAFIA, Role.DON, Role.CITIZEN, Role.CITIZEN, Role.CITIZEN])
    fx = night_pick(st, 1, 3, 0)
    assert any(type(e).__name__ == "EditPM" for e in fx)


# ---------------------------------------------------------------- resolve_night


def test_doctor_saves_victim():
    st = make_state([Role.DOCTOR, Role.CITIZEN, Role.CITIZEN, Role.MAFIA, Role.CITIZEN])
    night_pick(st, 4, 2, 0)  # mafia -> P2
    night_pick(st, 1, 2, 0)  # doctor -> P2
    fx = resolve_night(st, 100)
    assert st.by_seat(2).alive
    assert any(isinstance(e, SendGroup) and "спас" in e.text.lower() for e in fx)
    assert st.phase == Phase.DAY_DISCUSS


def test_godfather_kill_ignores_doctor():
    st = make_state(
        [Role.DOCTOR, Role.CITIZEN, Role.GODFATHER, Role.CITIZEN, Role.CITIZEN]
    )
    night_pick(st, 3, 2, 0)
    night_pick(st, 1, 2, 0)
    resolve_night(st, 100)
    assert not st.by_seat(2).alive
    assert st.phase == Phase.DAY_DISCUSS


def test_don_vote_has_double_weight():
    # don -> P3 (weight 2), single mafia -> P4 (weight 1): P3 dies
    st = make_state(
        [Role.DON, Role.MAFIA, Role.CITIZEN, Role.CITIZEN, Role.CITIZEN, Role.CITIZEN]
    )
    night_pick(st, 1, 3, 0)
    night_pick(st, 2, 4, 0)
    resolve_night(st, 100)
    assert not st.by_seat(3).alive
    assert st.by_seat(4).alive


def test_mafia_tie_no_kill():
    st = make_state(
        [
            Role.MAFIA,
            Role.MAFIA,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
        ]
    )
    night_pick(st, 1, 3, 0)
    night_pick(st, 2, 4, 0)
    resolve_night(st, 100)
    assert st.by_seat(3).alive and st.by_seat(4).alive


def test_sheriff_check_result():
    st = make_state([Role.SHERIFF, Role.MAFIA, Role.CITIZEN, Role.CITIZEN, Role.CITIZEN])
    night_pick(st, 1, 2, 0)
    fx = resolve_night(st, 100)
    pms = [e for e in fx if isinstance(e, SendPM) and e.user_id == 100]
    assert pms and "маф" in pms[0].text.lower()


def test_quiet_night_when_no_picks():
    st = make_state([Role.SHERIFF, Role.CITIZEN, Role.CITIZEN, Role.MAFIA, Role.CITIZEN])
    fx = resolve_night(st, 100)
    assert st.phase == Phase.DAY_DISCUSS
    assert any(isinstance(e, SendGroup) for e in fx)


# ---------------------------------------------------------------- vote


def test_majority_lynch():
    st = make_state(
        [
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.MAFIA,
        ]
    )
    st.phase = Phase.DAY_VOTE
    cast_vote(st, 1, 6)
    cast_vote(st, 2, 6)
    cast_vote(st, 3, 6)
    cast_vote(st, 4, 6)  # 4/6 = majority
    fx = resolve_vote(st, 100)
    assert not st.by_seat(6).alive
    assert st.phase in (Phase.NIGHT, Phase.ENDED, Phase.HUNTER)
    assert fx


def test_tie_no_execution():
    st = make_state(
        [
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.MAFIA,
            Role.MAFIA,
        ]
    )
    st.phase = Phase.DAY_VOTE
    cast_vote(st, 1, 5)
    cast_vote(st, 2, 6)
    cast_vote(st, 3, 5)
    cast_vote(st, 4, 6)
    resolve_vote(st, 100)
    assert st.by_seat(5).alive and st.by_seat(6).alive
    assert st.phase == Phase.NIGHT


def test_vote_self_rejected():
    st = make_state([Role.CITIZEN] * 5 + [Role.MAFIA])
    st.phase = Phase.DAY_VOTE
    with pytest.raises(EngineError):
        cast_vote(st, 1, 1)


def test_dead_cannot_vote():
    st = make_state([Role.CITIZEN] * 5 + [Role.MAFIA])
    st.phase = Phase.DAY_VOTE
    st.by_seat(1).alive = False
    with pytest.raises(EngineError, match="мертвы"):
        cast_vote(st, 1, 2)


# ---------------------------------------------------------------- winners


def test_town_wins_when_mafia_dead():
    st = make_state(
        [
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.MAFIA,
            Role.DOCTOR,
        ]
    )
    st.phase = Phase.DAY_VOTE
    cast_vote(st, 1, 5)
    cast_vote(st, 2, 5)
    cast_vote(st, 3, 5)
    cast_vote(st, 6, 5)
    resolve_vote(st, 100)
    assert st.phase == Phase.ENDED
    assert st.winner == "town"


def test_mafia_parity_win():
    st = make_state([Role.CITIZEN, Role.CITIZEN, Role.MAFIA, Role.MAFIA])
    st.phase = Phase.DAY_VOTE
    resolve_vote(st, 100)  # no lynch; mafia 2 >= town 2
    assert st.phase == Phase.ENDED
    assert st.winner == "mafia"


def test_clown_lynch_wins_solo():
    st = make_state(
        [Role.CLOWN, Role.CITIZEN, Role.CITIZEN, Role.MAFIA, Role.CITIZEN]
    )
    st.phase = Phase.DAY_VOTE
    cast_vote(st, 2, 1)
    cast_vote(st, 3, 1)
    cast_vote(st, 4, 1)
    resolve_vote(st, 100)
    assert st.clown_win
    assert st.phase == Phase.ENDED
    assert st.winner is not None


def test_clown_night_kill_wins_solo():
    st = make_state(
        [Role.CLOWN, Role.MAFIA, Role.CITIZEN, Role.CITIZEN, Role.CITIZEN]
    )
    night_pick(st, 2, 1, 0)
    resolve_night(st, 100)
    assert st.clown_win
    assert st.phase == Phase.ENDED


def test_clown_priority_over_parity():
    # killing clown ends game even though mafia would reach parity same night
    st = make_state(
        [Role.CLOWN, Role.MAFIA, Role.CITIZEN, Role.CITIZEN]
    )
    # alive: clown, mafia, 2 town. mafia kills clown -> solo, not mafia parity
    night_pick(st, 2, 1, 0)
    resolve_night(st, 100)
    assert st.phase == Phase.ENDED
    assert st.clown_win


# ---------------------------------------------------------------- hunter


def _hunt_state() -> E.GameState:
    return make_state(
        [Role.HUNTER, Role.CITIZEN, Role.CITIZEN, Role.MAFIA, Role.CITIZEN]
    )


def test_hunter_after_lynch_resume_night():
    st = _hunt_state()
    st.phase = Phase.DAY_VOTE
    cast_vote(st, 2, 1)
    cast_vote(st, 3, 1)
    cast_vote(st, 5, 1)
    resolve_vote(st, 100)
    assert st.phase == Phase.HUNTER
    fx = resolve_hunter(st, 2, 200)  # shoots townie, mafia still alive
    assert not st.by_seat(2).alive
    assert st.by_seat(4).alive
    assert st.phase == Phase.NIGHT
    assert st.day == 2
    assert fx


def test_hunter_after_night_resume_discuss():
    st = make_state(
        [Role.MAFIA, Role.HUNTER, Role.CITIZEN, Role.CITIZEN, Role.CITIZEN]
    )
    night_pick(st, 1, 2, 0)
    resolve_night(st, 100)
    assert st.phase == Phase.HUNTER
    assert st.resume_phase == Phase.DAY_DISCUSS
    resolve_hunter(st, 3, 200)
    assert st.phase == Phase.DAY_DISCUSS


def test_hunter_skip_shot():
    st = _hunt_state()
    st.phase = Phase.DAY_VOTE
    cast_vote(st, 2, 1)
    cast_vote(st, 3, 1)
    cast_vote(st, 5, 1)
    resolve_vote(st, 100)
    resolve_hunter(st, None, 200)
    assert st.phase == Phase.NIGHT
    assert all(p.alive for p in st.players if p.seat != 1)


def test_chained_hunter_shoots_back():
    # hunter shoots another hunter -> second hunter gets own shot
    st = make_state(
        [Role.HUNTER, Role.HUNTER, Role.CITIZEN, Role.CITIZEN, Role.MAFIA]
    )
    st.phase = Phase.DAY_VOTE
    cast_vote(st, 3, 1)
    cast_vote(st, 4, 1)
    cast_vote(st, 5, 1)
    resolve_vote(st, 100)
    assert st.phase == Phase.HUNTER and st.pending_hunter_seat == 1
    fx = resolve_hunter(st, 2, 200)  # shoots hunter P2
    assert st.phase == Phase.HUNTER
    assert st.pending_hunter_seat == 2
    assert not st.by_seat(2).alive
    assert any(isinstance(e, SendPM) for e in fx)
    resolve_hunter(st, None, 300)  # second hunter skips -> resume night
    assert st.phase == Phase.NIGHT
    assert st.day == 2


# ---------------------------------------------------------------- flow


def test_deadline_discuss_to_vote():
    st = make_state([Role.CITIZEN] * 5 + [Role.MAFIA])
    st.phase = Phase.DAY_DISCUSS
    st.deadline_ts = 10
    on_deadline(st, 20)
    assert st.phase == Phase.DAY_VOTE


def test_host_skip_night():
    st = make_state([Role.CITIZEN] * 5 + [Role.MAFIA])
    st.phase = Phase.NIGHT
    fx = host_skip(st, 100)
    assert st.phase == Phase.DAY_DISCUSS
    assert fx


def test_on_deadline_ended_noop():
    st = make_state([Role.CITIZEN] * 5 + [Role.MAFIA])
    st.phase = Phase.ENDED
    assert on_deadline(st, 1) == []


def test_night_action_wrong_phase():
    st = make_state([Role.CITIZEN] * 5 + [Role.MAFIA])
    st.phase = Phase.DAY_DISCUSS
    with pytest.raises(EngineError):
        night_pick(st, 6, 1, 0)


def test_roleless_player_cannot_act():
    st = make_state([Role.CITIZEN] * 5 + [Role.MAFIA])
    st.by_seat(1).role = None
    with pytest.raises(EngineError):
        night_pick(st, 1, 2, 0)
