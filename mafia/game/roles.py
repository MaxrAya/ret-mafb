from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from enum import StrEnum


class Role(StrEnum):
    CITIZEN = "citizen"
    MAFIA = "mafia"
    DON = "don"
    GODFATHER = "godfather"
    SHERIFF = "sheriff"
    DOCTOR = "doctor"
    CLOWN = "clown"
    HUNTER = "hunter"


class Team(StrEnum):
    TOWN = "town"
    MAFIA = "mafia"
    SOLO = "solo"


ROLE_TEAM: dict[Role, Team] = {
    Role.CITIZEN: Team.TOWN,
    Role.SHERIFF: Team.TOWN,
    Role.DOCTOR: Team.TOWN,
    Role.HUNTER: Team.TOWN,
    Role.MAFIA: Team.MAFIA,
    Role.DON: Team.MAFIA,
    Role.GODFATHER: Team.MAFIA,
    Role.CLOWN: Team.SOLO,
}

MAFIA_ROLES = {Role.MAFIA, Role.DON, Role.GODFATHER}


@dataclass(frozen=True)
class RoleInfo:
    name: str
    team: Team
    emoji: str
    desc: str


ROLE_INFO: dict[Role, RoleInfo] = {
    Role.CITIZEN: RoleInfo(
        "Мирный житель", Team.TOWN, "🧑",
        "Вы — простой житель. Днём ищите мафию и голосуйте против подозрительных.",
    ),
    Role.SHERIFF: RoleInfo(
        "Шериф", Team.TOWN, "🔍",
        "Каждую ночь проверяйте одного игрока: мафия он или нет.",
    ),
    Role.DOCTOR: RoleInfo(
        "Доктор", Team.TOWN, "💊",
        "Каждую ночь спасайте одного игрока — включая себя — от ночного убийства.",
    ),
    Role.HUNTER: RoleInfo(
        "Охотник", Team.TOWN, "🔫",
        "Если вас убьют — выстрелите в любого игрока в ответном порядке.",
    ),
    Role.MAFIA: RoleInfo(
        "Мафия", Team.MAFIA, "🔪",
        "Ночью выбираете жертву вместе с командой. Днём — сливайтесь с городом.",
    ),
    Role.DON: RoleInfo(
        "Дон", Team.MAFIA, "🎩",
        "Босс мафии: ваш ночной голос весит двойной. Ведите команду к победе.",
    ),
    Role.GODFATHER: RoleInfo(
        "Сильный мафиози", Team.MAFIA, "💀",
        "Ночные убийства вашей банды не лечатся доктором.",
    ),
    Role.CLOWN: RoleInfo(
        "Клоун", Team.SOLO, "🤡",
        "Ваша цель — погибнуть от рук города (казнь) или мафии (ночь). Тогда победа за вами!",
    ),
}


@dataclass
class GameSettings:
    min_players: int = 5
    max_players: int = 15
    discuss_s: int = 120
    vote_s: int = 90
    night_s: int = 60
    hunter_s: int = 45
    rated: bool = True
    anonymous_vote: bool = False
    use_don: bool = True
    use_godfather: bool = False
    use_sheriff: bool = True
    use_doctor: bool = True
    use_clown: bool = False
    use_hunter: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str | None) -> GameSettings:
        if not raw:
            return cls()
        data = json.loads(raw)
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


class RolePoolError(ValueError):
    pass


def auto_role_counts(n: int, s: GameSettings) -> dict[Role, int]:
    if n < s.min_players:
        raise RolePoolError(f"Нужно минимум {s.min_players} игроков")

    mafia_slots = max(1, n // 4)
    don = 1 if s.use_don and mafia_slots >= 2 else 0
    godfather = 1 if s.use_godfather and mafia_slots - don >= 2 else 0
    mafia_regular = mafia_slots - don - godfather

    sheriff = 1 if s.use_sheriff else 0
    doctor = 1 if s.use_doctor else 0
    hunter = 1 if s.use_hunter else 0
    clown = 1 if s.use_clown else 0

    fixed = mafia_regular + don + godfather + sheriff + doctor + hunter + clown
    citizens = n - fixed
    if citizens < 1:
        raise RolePoolError(
            f"При этих ролях нужно минимум {fixed + 1} игроков"
        )

    counts: dict[Role, int] = {Role.CITIZEN: citizens}
    for role, cnt in (
        (Role.MAFIA, mafia_regular),
        (Role.DON, don),
        (Role.GODFATHER, godfather),
        (Role.SHERIFF, sheriff),
        (Role.DOCTOR, doctor),
        (Role.HUNTER, hunter),
        (Role.CLOWN, clown),
    ):
        if cnt:
            counts[role] = cnt
    return counts
