from __future__ import annotations

from types import SimpleNamespace

from mafia.game import achievements as A


def test_first_game():
    st = SimpleNamespace(games=1, wins=0, best_streak=0, rating=1000)
    got = A.check(st, set())
    assert any(a.key == "first_game" for a in got)


def test_already_have_skipped():
    st = SimpleNamespace(games=1, wins=0, best_streak=0, rating=1000)
    got = A.check(st, {"first_game"})
    assert not any(a.key == "first_game" for a in got)


def test_rating_brackets():
    st = SimpleNamespace(games=50, wins=10, best_streak=5, rating=1500)
    keys = {a.key for a in A.check(st, set())}
    assert "rating_1200" in keys
    assert "rating_1500" in keys
    assert "rating_1800" not in keys
    assert "streak_5" in keys


def test_none_stats_safe():
    st = SimpleNamespace()
    got = A.check(st, set())
    assert got == []  # games defaults to 0


def test_unique_keys():
    keys = [a.key for a in A.ACHIEVEMENTS]
    assert len(keys) == len(set(keys))
