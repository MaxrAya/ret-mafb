from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Achievement:
    key: str
    emoji: str
    title: str
    desc: str


ACHIEVEMENTS: list[Achievement] = [
    Achievement("first_game", "🎬", "Дебют", "Сыграть первую партию"),
    Achievement("first_win", "🎉", "Первая победа", "Одержать первую победу"),
    Achievement("games_10", "🎞", "Регуляр", "Сыграть 10 партий"),
    Achievement("games_50", "📼", "Ветеран", "Сыграть 50 партий"),
    Achievement("games_100", "📀", "Легенда стола", "Сыграть 100 партий"),
    Achievement("streak_5", "🔥", "Огонь", "Выиграть 5 партий подряд"),
    Achievement("rating_1200", "🥉", "Бронза", "Достичь рейтинга 1200"),
    Achievement("rating_1500", "🥈", "Серебро", "Достичь рейтинга 1500"),
    Achievement("rating_1800", "🥇", "Золото", "Достичь рейтинга 1800"),
    Achievement("wins_mafia_5", "🔪", "Семья", "5 побед за мафию"),
    Achievement("wins_town_5", "🏙️", "Гражданин", "5 побед за город"),
    Achievement("wins_clown_1", "🤡", "Шут дня", "Победа за клоуна"),
    Achievement("checks_20", "🔍", "Детектив", "20 проверок шерифом"),
    Achievement("saves_10", "💊", "Хирург", "10 спасений доктором"),
    Achievement("shots_5", "🔫", "Револьвер", "5 выстрелов охотника"),
    Achievement("kills_10", "🌙", "Ночная работа", "10 ночных убийств"),
    Achievement("votes_25", "⚖️", "Совесть города", "25 голосов на казнённых"),
    Achievement("flawless_1", "🦅", "Бессмертный", "Выиграть, ни разу не умер"),
    Achievement("tournaments_1", "🏆", "Чемпион", "Победить в турнире"),
]

ACH_BY_KEY: dict[str, Achievement] = {a.key: a for a in ACHIEVEMENTS}


def check(stats, have: set[str]) -> list[Achievement]:
    """Return newly unlocked achievements for a stats-like object."""

    def val(name: str) -> int:
        return int(getattr(stats, name, 0) or 0)

    candidates: list[tuple[str, bool]] = [
        ("first_game", val("games") >= 1),
        ("first_win", val("wins") >= 1),
        ("games_10", val("games") >= 10),
        ("games_50", val("games") >= 50),
        ("games_100", val("games") >= 100),
        ("streak_5", val("best_streak") >= 5),
        ("rating_1200", val("rating") >= 1200),
        ("rating_1500", val("rating") >= 1500),
        ("rating_1800", val("rating") >= 1800),
        ("wins_mafia_5", val("wins_mafia") >= 5),
        ("wins_town_5", val("wins_town") >= 5),
        ("wins_clown_1", val("wins_clown") >= 1),
        ("checks_20", val("checks") >= 20),
        ("saves_10", val("saves") >= 10),
        ("shots_5", val("hunter_shots") >= 5),
        ("kills_10", val("night_kills") >= 10),
        ("votes_25", val("good_votes") >= 25),
        ("flawless_1", val("flawless_wins") >= 1),
        ("tournaments_1", val("tournaments_wins") >= 1),
    ]
    return [ACH_BY_KEY[k] for k, ok in candidates if ok and k not in have]
