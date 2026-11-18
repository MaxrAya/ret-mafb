from __future__ import annotations

import html

from mafia.game.roles import ROLE_INFO, Role

WINNER_TOWN = "town"
WINNER_MAFIA = "mafia"
WINNER_SOLO = "solo"


def _e(text: str) -> str:
    return html.escape(text, quote=False)

WINNER_TITLE = {
    WINNER_TOWN: "🏙️ ПОБЕДА ГОРОДА",
    WINNER_MAFIA: "🔪 ПОБЕДА МАФИИ",
    WINNER_SOLO: "🤡 ПОБЕДА КЛОУНА",
}


def game_start(n: int) -> str:
    return (
        f"🎲 <b>Игра началась!</b> Игроков: {n}\n"
        "Роли разосланы в личные сообщения.\n"
        "Кто не получил роль — напишите боту /start в личке."
    )


def night_banner(day: int) -> str:
    return f"🌙 <b>Ночь {day}.</b> Город засыпает… Всё тихо."


def day_banner(day: int, discuss_s: int, players: list[tuple[int, str]]) -> str:
    mins = max(1, discuss_s // 60)
    lst = "\n".join(f"{s}. {_e(n)}" for s, n in players)
    return (
        f"☀️ <b>День {day}.</b> Обсуждение ({mins} мин).\n"
        f"Живые игроки:\n{lst}\n\n"
        "Следом — голосование."
    )


def vote_open(day: int, vote_s: int, players: list[tuple[int, str]]) -> str:
    mins = max(1, vote_s // 60)
    lst = "\n".join(f"{s}. {_e(n)}" for s, n in players)
    return (
        f"🗳 <b>Голосование {day}.</b> Время: {mins} мин.\n"
        f"Кандидаты:\n{lst}\n\n"
        "Нажмите на имя игрока, чтобы голосовать. Голос можно изменить."
    )


def vote_tally_text(
    day: int,
    deadline_text: str,
    players: list[tuple[int, str]],
    tally: dict[int, int],
    votes_from: dict[int, int],
    anonymous: bool,
) -> str:
    names = dict(players)
    if anonymous:
        rows = [f"{_e(names[s])} — {c}" for s, c in sorted(tally.items(), key=lambda x: -x[1])]
        head = "Текущие голоса (анонимно):"
    else:
        rows = [
            f"{_e(names[v])} → {_e(names[t])}" for v, t in sorted(votes_from.items())
        ]
        head = "Текущие голоса:"
    body = "\n".join(rows) if rows else "пока пусто"
    return f"🗳 <b>Голосование {day}</b> · {deadline_text}\n{head}\n{body}"


def role_pm(role: Role, teammates: list[str], day: int) -> str:
    info = ROLE_INFO[role]
    text = f"{info.emoji} <b>Ваша роль: {info.name}</b>\n\n{info.desc}"
    if teammates:
        mates = ", ".join(_e(m) for m in teammates)
        text += f"\n\nВаша команда: {mates}"
    return text


def night_prompt_mafia(day: int, role: Role, allies: list[str], tally: list[str]) -> str:
    info = ROLE_INFO[role]
    allies_txt = ", ".join(_e(a) for a in allies) if allies else "—"
    tally_txt = "\n".join(_e(t) for t in tally) if tally else "пока никто не выбирал"
    return (
        f"🌙 <b>Ночь {day}.</b> {info.emoji} Вы — {info.name}.\n"
        f"Союзники: {allies_txt}\n\n"
        f"Голос за жертву (кнопкой):\n{tally_txt}\n\n"
        "Можно писать текстовые сообщения — они уйдут в чат мафии."
    )


def night_prompt_sheriff(day: int) -> str:
    return f"🌙 <b>Ночь {day}.</b> 🔍 Вы — Шериф. Кого проверить?"


def night_prompt_doctor(day: int) -> str:
    return f"🌙 <b>Ночь {day}.</b> 💊 Вы — Доктор. Кого спасти от убийства?"


def night_prompt_sleep(day: int, role: Role) -> str:
    info = ROLE_INFO[role]
    return f"🌙 <b>Ночь {day}.</b> {info.emoji} Вы — {info.name}. Спокойной ночи."


def sheriff_result(name: str, is_mafia: bool) -> str:
    mark = "МАФИЯ" if is_mafia else "не мафия"
    return f"🔍 Результат проверки: <b>{_e(name)}</b> — {mark}."


def morning_quiet(day: int) -> str:
    return f"☀️ Утро дня {day}. Ночь прошла спокойно — жертв нет."


def morning_saved(day: int) -> str:
    return (
        f"☀️ Утро дня {day}. Было нападение, но доктор спас жертву! "
        "Жертв нет."
    )


def morning_body(day: int, name: str, role: Role) -> str:
    info = ROLE_INFO[role]
    return (
        f"☀️ Утро дня {day}. Находят тело: <b>{_e(name)}</b>.\n"
        f"Роль: {info.emoji} {info.name}."
    )


def lynch_result(name: str, role: Role) -> str:
    info = ROLE_INFO[role]
    return (
        f"⚖️ Голосование завершено. Город казнит <b>{_e(name)}</b>.\n"
        f"Роль: {info.emoji} {info.name}."
    )


def lynch_none(day: int, top_count: int, alive: int) -> str:
    return (
        f"⚖️ Голосование завершено: нет большинства "
        f"({top_count}/{alive}). Никто не казнён."
    )


def hunter_prompt(day: int, dead_name: str) -> str:
    return (
        f"🔫 <b>Охотник погиб!</b> {_e(dead_name)} может выстрелить в ответ.\n"
        "Выберите цель (кнопка) или пропустите выстрел."
    )


def hunter_group_prompt(dead_name: str) -> str:
    return "🔫 Охотник погиб и может выстрелить в ответ. Ожидаем выбор цели…"


def hunter_shot(shooter: str, target: str, role: Role) -> str:
    info = ROLE_INFO[role]
    return (
        f"🔫 {_e(shooter)}: выстрел в <b>{_e(target)}</b>.\n"
        f"Жертва: {info.emoji} {info.name}."
    )


def hunter_no_shot(shooter: str) -> str:
    return f"🔫 {_e(shooter)} пропускает выстрел."


def end_message(
    winner: str,
    reveal: list[tuple[str, str, bool]],
) -> str:
    """reveal: (name, role_key, alive)."""
    title = WINNER_TITLE[winner]
    rows = []
    for name, role_key, alive in reveal:
        info = ROLE_INFO[Role(role_key)]
        status = "✅" if alive else "💀"
        rows.append(f"{info.emoji} {_e(name)} — {info.name} {status}")
    return f"<b>{title}</b>\n\nВсе роли:\n" + "\n".join(rows)
