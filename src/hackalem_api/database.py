from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str):
    if database_url.startswith("sqlite:"):
        if database_url == "sqlite:///:memory:":
            return create_engine(database_url, connect_args={"check_same_thread": False}, pool_pre_ping=True)
        db_path = database_url.removeprefix("sqlite:///")
        Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        return create_engine(database_url, connect_args={"check_same_thread": False}, pool_pre_ping=True)
    return create_engine(database_url, pool_pre_ping=True)


def make_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
