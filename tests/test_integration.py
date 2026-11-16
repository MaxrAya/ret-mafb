from __future__ import annotations

import time

import pytest

from mafia.db import repo
from mafia.db.session import create_schema, dispose_db, init_db, session_scope
from mafia.game import engine
from mafia.game.engine import Phase
from mafia.game.roles import GameSettings, Team
from mafia.runner import Runner


class _Msg:
    message_id = 777


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple] = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append(("msg", chat_id, text))
        return _Msg()

    async def send_animation(self, chat_id, animation, **kw):
        self.sent.append(("anim", chat_id, animation))
        return _Msg()

    async def edit_message_text(self, *a, **k):
        return None

    async def edit_message_caption(self, *a, **k):
        return None

    async def edit_message_reply_markup(self, *a, **k):
        return None

    async def ban_chat_member(self, *a, **k):
        return None

    async def restrict_chat_member(self, *a, **k):
        return None


@pytest.fixture
async def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    await create_schema()
    yield
    await dispose_db()


async def test_full_flow(db):
    bot = FakeBot()
    runner = Runner(bot)  # type: ignore[arg-type]
    now = int(time.time())
    raw = [(1000 + i, f"P{i}") for i in range(6)]

    mid = await runner.start_game(-500, 1000, raw, GameSettings(), True, None)
    assert mid > 0

    # night -> discuss
    st = await runner.run(mid, lambda s: engine.host_skip(s, now))
    assert st is not None and st.phase == Phase.DAY_DISCUSS

    # discuss -> vote
    st = await runner.run(mid, lambda s: engine.open_vote(s, now + 10))
    assert st is not None and st.phase == Phase.DAY_VOTE

    # vote: majority on seat 1
    def vote_op(s):
        for seat in (2, 3, 4, 5):
            engine.cast_vote(s, seat, 1)
        return []

    st = await runner.run(mid, vote_op)
    assert st is not None
    st = await runner.run(mid, lambda s: engine.resolve_vote(s, now + 20))
    assert st is not None
    assert st.phase in (Phase.NIGHT, Phase.HUNTER, Phase.ENDED)

    if st.phase != Phase.ENDED:
        # vote persisted for current day (game continues)
        async with session_scope() as session:
            state = await repo.load_state(session, mid)
        assert state is not None
        assert state.day == st.day
    else:
        # seat 1 was mafia -> town won, match finished
        assert st.winner is not None


async def test_night_kill_roundtrip(db):
    bot = FakeBot()
    runner = Runner(bot)  # type: ignore[arg-type]
    now = int(time.time())
    raw = [(2000 + i, f"Q{i}") for i in range(6)]
    mid = await runner.start_game(-501, 2000, raw, GameSettings(), True, None)

    async with session_scope() as session:
        state = await repo.load_state(session, mid)
    assert state is not None
    mafia = [p for p in state.players if p.team == Team.MAFIA]
    town = [p for p in state.players if p.team != Team.MAFIA]
    assert mafia and town
    victim = town[0]

    def night_op(s):
        for m in mafia:
            engine.night_pick(s, m.seat, victim.seat, now)
        return []

    st = await runner.run(mid, night_op)
    assert st is not None and st.phase == Phase.NIGHT
    # pick persisted
    async with session_scope() as session:
        state = await repo.load_state(session, mid)
    assert state is not None
    assert victim.seat in state.night.values()

    st = await runner.run(mid, lambda s: engine.resolve_night(s, now + 60))
    assert st is not None
    # no doctor pick was made, victim must die (clown/hunter off by default)
    assert st.phase == Phase.DAY_DISCUSS
    assert not st.by_seat(victim.seat).alive
    # day still 1 (increments when next night opens); reload keeps state
    async with session_scope() as session:
        state = await repo.load_state(session, mid)
    assert state is not None
    assert state.day == 1
    assert victim.seat in state.night.values()


async def test_finalize_updates_stats(db):
    bot = FakeBot()
    runner = Runner(bot)  # type: ignore[arg-type]
    raw = [(3000 + i, f"R{i}") for i in range(6)]
    mid = await runner.start_game(-502, 3000, raw, GameSettings(), True, None)

    def end_town(s):
        for p in s.players:
            if p.team == Team.MAFIA:
                p.alive = False
        return engine._end(s, engine.T.WINNER_TOWN)  # noqa: SLF001

    st = await runner.run(mid, end_town)
    assert st is not None and st.phase == Phase.ENDED

    async with session_scope() as session:
        for i in range(6):
            stats = await repo.get_stats(session, 3000 + i)
            assert stats.games == 1
            assert stats.wins + stats.losses == 1
        # rating table message was attempted
    assert any(x[0] == "msg" for x in bot.sent)


async def test_abort_unlocks(db):
    bot = FakeBot()
    runner = Runner(bot)  # type: ignore[arg-type]
    raw = [(4000 + i, f"S{i}") for i in range(5)]
    mid = await runner.start_game(-503, 4000, raw, GameSettings(), True, None)
    await runner.abort(mid, "test")
    async with session_scope() as session:
        state = await repo.load_state(session, mid)
    assert state is None  # not active anymore


async def test_force_end_with_rating(db):
    bot = FakeBot()
    runner = Runner(bot)  # type: ignore[arg-type]
    raw = [(5000 + i, f"F{i}") for i in range(6)]
    mid = await runner.start_game(-504, 5000, raw, GameSettings(), True, None)

    await runner.force_end(mid, "mafia")

    async with session_scope() as session:
        state = await repo.load_state(session, mid)
        assert state is None  # match finished
        for i in range(6):
            stats = await repo.get_stats(session, 5000 + i)
            assert stats.games == 1
            assert stats.wins + stats.losses == 1
    # end banner was sent
    assert any(x[0] in ("msg", "anim") for x in bot.sent)
