from __future__ import annotations

K_FACTOR = 32
SOLO_WIN = 24
RATING_FLOOR = 0


def _expected(ra: float, rb: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


def _avg(values: list[int]) -> float:
    return sum(values) / len(values) if values else 1000.0


def compute_deltas(
    ratings: dict[int, int],
    teams: dict[int, str],
    winner: str,
) -> dict[int, int]:
    """ratings: user_id -> rating; teams: user_id -> town|mafia|solo.

    Returns user_id -> delta (0-sum per side, solo is handled separately).
    """
    deltas: dict[int, int] = {uid: 0 for uid in ratings}
    town = [uid for uid, t in teams.items() if t == "town"]
    mafia = [uid for uid, t in teams.items() if t == "mafia"]
    solo = [uid for uid, t in teams.items() if t == "solo"]

    if winner == "solo":
        for uid in solo:
            deltas[uid] = SOLO_WIN
        others = [uid for uid in ratings if uid not in solo]
        if others:
            share = max(1, SOLO_WIN // len(others))
            for uid in others:
                deltas[uid] = -share
        return _apply_floor(deltas, ratings)

    if not town or not mafia:
        return deltas

    if winner == "town":
        win_side, lose_side = town, mafia
    elif winner == "mafia":
        win_side, lose_side = mafia, town
    else:
        return deltas

    r_win = _avg([ratings[uid] for uid in win_side])
    r_lose = _avg([ratings[uid] for uid in lose_side])
    e = _expected(r_win, r_lose)
    d_each = max(1, round(K_FACTOR * (1.0 - e)))
    total_win = d_each * len(win_side)

    for uid in win_side:
        deltas[uid] = d_each

    # exact zero-sum: losers split the winners' total
    base = total_win // len(lose_side)
    rem = total_win - base * len(lose_side)
    for i, uid in enumerate(lose_side):
        deltas[uid] = -(base + (1 if i < rem else 0))

    return _apply_floor(deltas, ratings)


def _apply_floor(deltas: dict[int, int], ratings: dict[int, int]) -> dict[int, int]:
    out: dict[int, int] = {}
    for uid, d in deltas.items():
        current = ratings.get(uid, 1000)
        if current + d < RATING_FLOOR:
            d = RATING_FLOOR - current
        out[uid] = d
    return out
