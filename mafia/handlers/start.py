from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

router = Router(name="start")

HELP_TEXT = (
    "🗂 <b>Команды</b>\n\n"
    "<b>Игра</b>\n"
    "/mafia — создать лобби и начать сбор игроков\n"
    "/game — состояние текущей партии\n"
    "/skip — пропустить фазу (хост)\n\n"
    "<b>Профиль</b>\n"
    "/profile — ваша статистика (или ответом на сообщение — чужая)\n"
    "/top — рейтинг игроков\n"
    "/achievements — достижения\n"
    "/matches — последние партии чата\n\n"
    "<b>Турниры</b>\n"
    "/tournament create [раундов] [очков за победу]\n"
    "/tournament join | leave | start | top | cancel\n\n"
    "<b>Настройка чата</b>\n"
    "/setgif night|day|vote|end|start — ответьте командой на гифку, "
    "чтобы бот использовал её на фазах\n\n"
    "Боту нужны права администратора: <i>ограничение участников</i> "
    "и <i>удаление сообщений</i>."
)

RULES_TEXT = (
    "📜 <b>Правила</b>\n\n"
    "В городе воюют мирные жители и мафия.\n\n"
    "🌙 <b>Ночь</b> — в группе тишина (все в мьюте). Шериф проверяет, "
    "доктор спасает, мафия выбирает жертву в ЛС бота.\n"
    "☀️ <b>День</b> — обсуждение, затем голосование: большинство казнит "
    "игрока. Мёртвые молчат до конца партии.\n\n"
    "🏙️ Город побеждает, убив всю мафию.\n"
    "🔪 Мафия побеждает, сравнявшись по числу с городом.\n"
    "🤡 Клоун побеждает, если его казнили или убила мафия.\n\n"
    "Медиа и скриншоты во время партии запрещены — только текст."
)


@router.message(CommandStart())
async def cmd_start(msg: Message) -> None:
    where = msg.chat.type
    if where == "private":
        await msg.answer(
            "🎭 <b>Мафия</b> — бот для настоящих партий в группах.\n\n"
            "Добавьте меня в группу, выдайте права администратора "
            "(ограничение участников + удаление сообщений) и напишите /mafia.\n\n"
            + HELP_TEXT,
        )
    else:
        await msg.answer(
            "🎭 Я готов играть! Соберите партию командой /mafia.\n\n"
            "Подробности: /help · Правила: /rules",
        )


@router.message(Command("help"))
async def cmd_help(msg: Message) -> None:
    await msg.answer(HELP_TEXT)


@router.message(Command("rules"))
async def cmd_rules(msg: Message) -> None:
    await msg.answer(RULES_TEXT)
