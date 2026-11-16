from __future__ import annotations

from mafia.game import rating


def test_town_win_zero_sum():
    ratings = {1: 1000, 2: 1000, 3: 1000, 4: 1000, 5: 1000, 6: 1000}
    teams = {1: "town", 2: "town", 3: "town", 4: "town", 5: "town", 6: "mafia"}
    d = rating.compute_deltas(ratings, teams, "town")
    assert sum(d.values()) == 0
    assert d[1] > 0
    assert d[6] < 0


def test_mafia_win_flips_signs():
    ratings = {1: 1000, 2: 1000, 3: 1000, 4: 1000, 5: 1000, 6: 1000}
    teams = {1: "town", 2: "town", 3: "town", 4: "town", 5: "town", 6: "mafia"}
    d = rating.compute_deltas(ratings, teams, "mafia")
    assert d[6] > 0
    assert d[1] < 0


def test_equal_ratings_delta_at_least_one():
    ratings = {1: 1000, 2: 1000, 3: 1000, 4: 1000}
    teams = {1: "town", 2: "town", 3: "mafia", 4: "mafia"}
    d = rating.compute_deltas(ratings, teams, "town")
    assert d[1] == rating.K_FACTOR // 2 or d[1] >= 1


def test_floor_applies():
    ratings = {1: 0, 2: 1000, 3: 1000, 4: 1000}
    teams = {1: "town", 2: "town", 3: "mafia", 4: "mafia"}
    d = rating.compute_deltas(ratings, teams, "mafia")
    assert 0 + d[1] >= rating.RATING_FLOOR


def test_solo_win():
    ratings = {1: 1000, 2: 1000, 3: 1000, 4: 1000, 5: 1000}
    teams = {1: "solo", 2: "town", 3: "town", 4: "mafia", 5: "mafia"}
    d = rating.compute_deltas(ratings, teams, "solo")
    assert d[1] == rating.SOLO_WIN
    assert d[2] < 0
    # solo losers pay full share across others
    assert sum(v for k, v in d.items() if k != 1) == -rating.SOLO_WIN


def test_unknown_winner_zero():
    ratings = {1: 1000, 2: 1000}
    teams = {1: "town", 2: "mafia"}
    d = rating.compute_deltas(ratings, teams, "draw")
    assert all(v == 0 for v in d.values())
