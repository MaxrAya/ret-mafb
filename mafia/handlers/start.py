from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from mafia.db import repo
from mafia.db.session import session_scope
from mafia.handlers import profile as ph

router = Router(name="start")

HELP_TEXT = (
    "🗂 <b>Все команды</b>\n\n"
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
    "<b>Уведомления</b>\n"
    "/subscribe — ЛС-уведомление, когда в группе собирают партию\n"
    "/unsubscribe — выключить уведомления\n\n"
    "<b>После партии</b>\n"
    "Кнопка «🔁 Ещё партия» под итогами — реванш тем же составом "
    "(для хоста). В настройках лобби — пресеты: ⚡ Быстрая, "
    "🎲 Классика, 🐢 Длинная.\n\n"
    "<b>Админ чата</b>\n"
    "/forcend [town|mafia] — завершить партию с подсчётом рейтинга\n"
    "/admin_skip — пропустить фазу (не только хост)\n"
    "/admin_stop — остановить партию без рейтинга\n\n"
    "<b>Владелец бота</b>\n"
    "/admin_stats — статистика бота\n"
    "/admin_reset — сбросить статистику игрока (ответом или ID)\n"
    "/admin_broadcast — рассылка всем игрокам\n\n"
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

MENU_TEXT = (
    "🎭 <b>Мафия</b> — бот для партий в группах.\n\n"
    "Как играть: добавь меня в группу → дай права администратора "
    "(ограничение участников + удаление сообщений) → напиши /mafia.\n\n"
    "Выбери раздел кнопками ниже."
)

BACK_KB = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Меню", callback_data="pm:back")]
    ]
)


def menu_kb(sub: bool) -> InlineKeyboardMarkup:
    sub_btn = "🔔 Уведомления: вкл" if sub else "🔕 Уведомления: выкл"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📜 Правила", callback_data="pm:rules"),
                InlineKeyboardButton(text="🗂 Команды", callback_data="pm:help"),
            ],
            [
                InlineKeyboardButton(
                    text="👤 Профиль", callback_data="pm:profile"
                ),
                InlineKeyboardButton(
                    text="🏆 Достижения", callback_data="pm:ach"
                ),
            ],
            [
                InlineKeyboardButton(text="🌍 Топ", callback_data="pm:top"),
                InlineKeyboardButton(text=sub_btn, callback_data="pm:sub"),
            ],
        ]
    )


async def _sub_state(uid: int) -> bool:
    async with session_scope() as session:
        return await repo.is_sub(session, uid)


async def _edit(cb: CallbackQuery, text: str, markup: InlineKeyboardMarkup) -> None:
    assert cb.message is not None
    try:
        await cb.message.edit_text(
            text, parse_mode="HTML", reply_markup=markup
        )
    except Exception:
        pass
    await cb.answer()


@router.message(CommandStart())
async def cmd_start(msg: Message) -> None:
    if msg.chat.type == "private":
        assert msg.from_user is not None
        sub = await _sub_state(msg.from_user.id)
        await msg.answer(
            MENU_TEXT, parse_mode="HTML", reply_markup=menu_kb(sub)
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


@router.callback_query(F.data == "pm:back")
async def cb_pm_back(cb: CallbackQuery) -> None:
    assert cb.from_user is not None
    sub = await _sub_state(cb.from_user.id)
    await _edit(cb, MENU_TEXT, menu_kb(sub))


@router.callback_query(F.data == "pm:rules")
async def cb_pm_rules(cb: CallbackQuery) -> None:
    await _edit(cb, RULES_TEXT, BACK_KB)


@router.callback_query(F.data == "pm:help")
async def cb_pm_help(cb: CallbackQuery) -> None:
    await _edit(cb, HELP_TEXT, BACK_KB)


@router.callback_query(F.data == "pm:profile")
async def cb_pm_profile(cb: CallbackQuery) -> None:
    assert cb.from_user is not None
    text = await ph.profile_html(
        cb.from_user.id, cb.from_user.full_name
    )
    if text is None:
        await cb.answer("Не нашёл такого игрока.", show_alert=True)
        return
    await _edit(cb, text, BACK_KB)


@router.callback_query(F.data == "pm:ach")
async def cb_pm_ach(cb: CallbackQuery) -> None:
    assert cb.from_user is not None
    text = await ph.ach_html(cb.from_user.id, cb.from_user.full_name)
    if text is None:
        await cb.answer("Не нашёл такого игрока.", show_alert=True)
        return
    await _edit(cb, text, BACK_KB)


@router.callback_query(F.data == "pm:top")
async def cb_pm_top(cb: CallbackQuery) -> None:
    body = await ph._global_top()
    await _edit(
        cb, "🌍 <b>Глобальный рейтинг</b>\n\n" + body, BACK_KB
    )


@router.callback_query(F.data == "pm:sub")
async def cb_pm_sub(cb: CallbackQuery) -> None:
    assert cb.from_user is not None and cb.message is not None
    uid = cb.from_user.id
    async with session_scope() as session:
        if await repo.is_sub(session, uid):
            await repo.del_sub(session, uid)
            on = False
        else:
            await repo.add_sub(session, uid)
            on = True
    try:
        await cb.message.edit_text(
            MENU_TEXT, parse_mode="HTML", reply_markup=menu_kb(on)
        )
    except Exception:
        pass
    await cb.answer(
        "🔔 Уведомления включены." if on else "🔕 Уведомления выключены."
    )
