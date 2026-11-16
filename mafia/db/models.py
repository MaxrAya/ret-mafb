from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlayerStats(Base):
    __tablename__ = "player_stats"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rating: Mapped[int] = mapped_column(Integer, default=1000)
    games: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    streak: Mapped[int] = mapped_column(Integer, default=0)
    best_streak: Mapped[int] = mapped_column(Integer, default=0)
    wins_mafia: Mapped[int] = mapped_column(Integer, default=0)
    wins_town: Mapped[int] = mapped_column(Integer, default=0)
    wins_clown: Mapped[int] = mapped_column(Integer, default=0)
    checks: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    hunter_shots: Mapped[int] = mapped_column(Integer, default=0)
    night_kills: Mapped[int] = mapped_column(Integer, default=0)
    good_votes: Mapped[int] = mapped_column(Integer, default=0)
    flawless_wins: Mapped[int] = mapped_column(Integer, default=0)
    tournaments_wins: Mapped[int] = mapped_column(Integer, default=0)
    achievements_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChatStats(Base):
    __tablename__ = "chat_stats"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rating: Mapped[int] = mapped_column(Integer, default=1000)
    games: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)


class Lobby(Base):
    __tablename__ = "lobbies"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    host_id: Mapped[int] = mapped_column(BigInteger)
    settings_json: Mapped[str] = mapped_column(Text, default="{}")
    msg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tournament_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournaments.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LobbyPlayer(Base):
    __tablename__ = "lobby_players"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), default="")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    host_id: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|finished|aborted
    phase: Mapped[str] = mapped_column(String(16), default="night")
    day: Mapped[int] = mapped_column(Integer, default=1)
    deadline_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    winner: Mapped[str | None] = mapped_column(String(16), nullable=True)  # town|mafia|solo
    settings_json: Mapped[str] = mapped_column(Text, default="{}")
    rated: Mapped[int] = mapped_column(Integer, default=1)
    tournament_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournaments.id"), nullable=True
    )
    vote_msg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    vote_msg_kind: Mapped[str | None] = mapped_column(String(8), nullable=True)
    banner_msg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    banner_kind: Mapped[str | None] = mapped_column(String(8), nullable=True)
    resume_phase: Mapped[str | None] = mapped_column(String(16), nullable=True)
    clown_win: Mapped[int] = mapped_column(Integer, default=0)
    pending_hunter_seat: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MatchPlayer(Base):
    __tablename__ = "match_players"

    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), primary_key=True)
    seat: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(256), default="")
    role: Mapped[str] = mapped_column(String(32), default="")
    team: Mapped[str] = mapped_column(String(16), default="town")
    alive: Mapped[int] = mapped_column(Integer, default=1)
    died_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    death_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pm_ok: Mapped[int] = mapped_column(Integer, default=1)
    won: Mapped[int] = mapped_column(Integer, default=0)
    night_msg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    self_heal_used: Mapped[int] = mapped_column(Integer, default=0)


class Vote(Base):
    __tablename__ = "votes"

    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), primary_key=True)
    day: Mapped[int] = mapped_column(Integer, primary_key=True)
    voter_seat: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_seat: Mapped[int] = mapped_column(Integer)


class NightAction(Base):
    __tablename__ = "night_actions"

    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), primary_key=True)
    day: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_seat: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[str] = mapped_column(String(32))
    target_seat: Mapped[int] = mapped_column(Integer)


class Achievement(Base):
    __tablename__ = "achievements"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    key: Mapped[str] = mapped_column(String(48), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Tournament(Base):
    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    host_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), default="lobby")  # lobby|playing|finished
    round_no: Mapped[int] = mapped_column(Integer, default=0)
    games_planned: Mapped[int] = mapped_column(Integer, default=5)
    points_win: Mapped[int] = mapped_column(Integer, default=3)
    msg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TournamentPlayer(Base):
    __tablename__ = "tournament_players"

    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), default="")
    points: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)


class ChatCooldown(Base):
    __tablename__ = "chat_cooldowns"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), primary_key=True)
    at_ts: Mapped[int] = mapped_column(BigInteger, default=0)


class ChatGif(Base):
    __tablename__ = "chat_gifs"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)  # start|night|day|vote|end
    file_id: Mapped[str] = mapped_column(String(255))
