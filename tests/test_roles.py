from __future__ import annotations

import pytest

from mafia.game.roles import GameSettings, Role, RolePoolError, auto_role_counts


def test_counts_six_players():
    s = GameSettings()
    counts = auto_role_counts(6, s)
    assert sum(counts.values()) == 6
    assert counts.get(Role.MAFIA, 0) == 1
    assert counts.get(Role.DON, 0) == 0  # slots < 2
    assert counts.get(Role.SHERIFF) == 1
    assert counts.get(Role.DOCTOR) == 1


def test_counts_eight_players_don():
    counts = auto_role_counts(8, GameSettings())
    assert sum(counts.values()) == 8
    assert counts.get(Role.DON) == 1
    assert counts.get(Role.MAFIA, 0) == 1


def test_godfather_slots():
    s = GameSettings(use_godfather=True)
    counts = auto_role_counts(12, s)
    assert counts.get(Role.GODFATHER) == 1
    assert counts.get(Role.DON) == 1
    assert counts.get(Role.MAFIA, 0) == 1


def test_too_few_players():
    with pytest.raises(RolePoolError):
        auto_role_counts(4, GameSettings())


def test_all_roles_overflow():
    s = GameSettings(use_hunter=True, use_clown=True, use_godfather=True)
    with pytest.raises(RolePoolError):
        auto_role_counts(5, s)


def test_settings_json_roundtrip():
    s = GameSettings(discuss_s=30, use_clown=True, anonymous_vote=True)
    again = GameSettings.from_json(s.to_json())
    assert again.discuss_s == 30
    assert again.use_clown is True
    assert again.anonymous_vote is True
    assert GameSettings.from_json(None) == GameSettings()
