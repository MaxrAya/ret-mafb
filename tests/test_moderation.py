from __future__ import annotations

from mafia.handlers.moderation import has_profanity

DIRTY = [
    "иди нахуй",
    "Пиздюк тут?",
    "Ёбаный рот",
    "мудак",
    "говно собачье",
    "шизовое дерьмо",
    "шлюха",
    "пидорас",
    "выебон",
    "сука ты что",
    "сучка",
    "заебал уже",
    "блядский день",
    "похуй на правила",
    "выдрочил",
]

CLEAN = [
    "привет всем",
    "Глеб пришёл на игру",
    "страх перед ночью",
    "гребать вёсла",
    "требный игрок",
    "требнуть ответа",
    "страховать баланс",
    "сукно белое",
    "бляха-муха",
    "клоун выиграл",
]


def test_profanity_detected():
    for case in DIRTY:
        assert has_profanity(case), case


def test_clean_text_passes():
    for case in CLEAN:
        assert not has_profanity(case), case
