from __future__ import annotations

from aiogram import Dispatcher

from mafia.handlers import admin, game, lobby, moderation, profile, start, tournament


def register_all(dp: Dispatcher) -> None:
    dp.include_router(start.router)
    dp.include_router(lobby.router)
    dp.include_router(game.router)
    dp.include_router(tournament.router)
    dp.include_router(profile.router)
    dp.include_router(admin.router)
    dp.include_router(moderation.router)
