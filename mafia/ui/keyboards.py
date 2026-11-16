from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from mafia.game.engine import GameState, GPlayer
from mafia.game.roles import GameSettings, Team


def _rows(buttons: list[InlineKeyboardButton], width: int = 2) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for b in buttons:
        kb.add(b)
    kb.adjust(width)
    return kb.as_markup()


def lobby_kb(has_host: bool) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text="➕ Войти", callback_data="lb:join"),
        InlineKeyboardButton(text="➖ Выйти", callback_data="lb:leave"),
    ]
    if has_host:
        buttons += [
            InlineKeyboardButton(text="▶️ Начать", callback_data="lb:start"),
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="st:menu"),
            InlineKeyboardButton(text="✖️ Отмена", callback_data="lb:cancel"),
        ]
    return _rows(buttons, 2)


def lobby_host_only_kb() -> InlineKeyboardMarkup:
    return _rows(
        [
            InlineKeyboardButton(text="▶️ Начать", callback_data="lb:start"),
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="st:menu"),
            InlineKeyboardButton(text="✖️ Отмена", callback_data="lb:cancel"),
        ],
        1,
    )


NUM_ADJ: dict[str, tuple[int, int, int]] = {
    "min": (4, 10, 1),
    "max": (5, 20, 1),
    "discuss": (30, 300, 30),
    "vote": (30, 240, 30),
    "night": (20, 180, 10),
}

ROLE_TOGGLES: dict[str, str] = {
    "don": "Дон",
    "godfather": "Сильный мафиози",
    "sheriff": "Шериф",
    "doctor": "Доктор",
    "clown": "Клоун",
    "hunter": "Охотник",
}


def settings_kb(s: GameSettings) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    on = "✅"
    off = "❌"

    def tog(key: str, label: str, active: bool) -> None:
        mark = on if active else off
        kb.add(
            InlineKeyboardButton(text=f"{mark} {label}", callback_data=f"st:tg:{key}")
        )

    def adj(label: str, key: str, value: int) -> None:
        kb.row(
            InlineKeyboardButton(text=f"− {label}", callback_data=f"st:adjm:{key}"),
            InlineKeyboardButton(text=f"{value}", callback_data="st:noop"),
            InlineKeyboardButton(text="+", callback_data=f"st:adj:{key}"),
        )

    adj("Игроков от", "min", s.min_players)
    adj("Игроков до", "max", s.max_players)
    adj("Обсуждение, с", "discuss", s.discuss_s)
    adj("Голосование, с", "vote", s.vote_s)
    adj("Ночь, с", "night", s.night_s)
    tog("rated", "Рейтинг", s.rated)
    tog("anon", "Анонимное голосование", s.anonymous_vote)
    kb.row(
        InlineKeyboardButton(text="———— роли ————", callback_data="st:noop"),
    )
    tog("don", "Дон", s.use_don)
    tog("godfather", "Сильный мафиози", s.use_godfather)
    tog("sheriff", "Шериф", s.use_sheriff)
    tog("doctor", "Доктор", s.use_doctor)
    tog("clown", "Клоун", s.use_clown)
    tog("hunter", "Охотник", s.use_hunter)
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="st:back"))
    return kb.as_markup()


def vote_kb(state: GameState) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in state.alive():
        kb.add(
            InlineKeyboardButton(
                text=f"{p.seat}. {p.name}",
                callback_data=f"v:{state.match_id}:{state.day}:{p.seat}",
            )
        )
    return kb.adjust(2).as_markup()


def _targets(
    state: GameState, prefix: str, actor: GPlayer | None, allow_self: bool
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in state.alive():
        if actor is not None and not allow_self and p.seat == actor.seat:
            continue
        kb.add(
            InlineKeyboardButton(
                text=f"{p.seat}. {p.name}",
                callback_data=f"{prefix}:{state.match_id}:{state.day}:{p.seat}",
            )
        )
    return kb.adjust(2).as_markup()


def night_kb(state: GameState, kind: str, actor_seat: int | None) -> InlineKeyboardMarkup:
    actor = state.by_seat(actor_seat) if actor_seat is not None else None
    if kind == "night_mafia":
        kb = InlineKeyboardBuilder()
        for p in state.alive():
            if p.team == Team.MAFIA:
                continue
            kb.add(
                InlineKeyboardButton(
                    text=f"{p.seat}. {p.name}",
                    callback_data=f"n:{state.match_id}:{state.day}:{p.seat}",
                )
            )
        return kb.adjust(2).as_markup()
    if kind == "night_sheriff":
        return _targets(state, "n", actor, allow_self=False)
    if kind == "night_doctor":
        allow_self = not (actor is not None and actor.self_heal_used)
        return _targets(state, "n", actor, allow_self=allow_self)
    return InlineKeyboardMarkup(inline_keyboard=[])


def hunter_kb(state: GameState) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in state.alive():
        kb.add(
            InlineKeyboardButton(
                text=f"{p.seat}. {p.name}",
                callback_data=f"h:{state.match_id}:{state.day}:{p.seat}",
            )
        )
    kb.row(
        InlineKeyboardButton(
            text="💤 Не стрелять", callback_data=f"h:{state.match_id}:{state.day}:0"
        )
    )
    return kb.adjust(2).as_markup()


def tournament_kb(can_start: bool) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text="➕ Войти", callback_data="tr:join"),
        InlineKeyboardButton(text="➖ Выйти", callback_data="tr:leave"),
    ]
    if can_start:
        buttons.append(
            InlineKeyboardButton(text="🏁 Начать турнир", callback_data="tr:start")
        )
    return _rows(buttons, 2)
