from __future__ import annotations

K_FACTOR = 32
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

    Returns user_id -> delta. Sum of deltas is always exactly 0:
    losers are clipped at RATING_FLOOR, winners are scaled down so the
    total gain equals the total loss actually collected.
    """
    deltas: dict[int, int] = {uid: 0 for uid in ratings}
    town = [uid for uid, t in teams.items() if t == "town"]
    mafia = [uid for uid, t in teams.items() if t == "mafia"]
    solo = [uid for uid, t in teams.items() if t == "solo"]

    if winner == "solo":
        if not solo:
            return deltas
        win_side, lose_side = solo, [uid for uid in ratings if uid not in solo]
    elif winner == "town":
        if not town or not mafia:
            return deltas
        win_side, lose_side = town, mafia
    elif winner == "mafia":
        if not town or not mafia:
            return deltas
        win_side, lose_side = mafia, town
    else:
        return deltas

    if not lose_side:
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

    return _zero_sum(deltas, ratings)


def _zero_sum(deltas: dict[int, int], ratings: dict[int, int]) -> dict[int, int]:
    out: dict[int, int] = {}
    for uid, d in deltas.items():
        current = ratings.get(uid, 1000)
        if current + d < RATING_FLOOR:
            d = RATING_FLOOR - current
        out[uid] = d
    total = sum(out.values())
    if total <= 0:
        return out
    # losers were clipped at the floor: scale winners down so sum == 0
    winners = [uid for uid, d in out.items() if d > 0]
    target = sum(out[uid] for uid in winners) - total
    base = target // len(winners)
    rem = target - base * len(winners)
    for i, uid in enumerate(winners):
        out[uid] = base + (1 if i < rem else 0)
    return out
