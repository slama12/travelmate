from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Classe de base déclarative SQLAlchemy 2.0 pour tous les modèles TravelMate."""


def normalize_sync_db_url(url: str) -> str:
    if url.startswith("sqlite+aiosqlite"):
        return url.replace("sqlite+aiosqlite", "sqlite", 1)
    if url.startswith("postgresql+asyncpg"):
        return url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    return url


class CompatAsyncConnection:
    """Adaptateur de connexion compatible async/sync sans dépendance C-extension greenlet."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._conn = None

    async def __aenter__(self) -> "CompatAsyncConnection":
        self._conn = self._engine.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._conn is not None:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
            self._conn.close()

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        assert self._conn is not None
        return self._conn.execute(statement, *args, **kwargs)

    async def run_sync(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        assert self._conn is not None
        return fn(self._conn, *args, **kwargs)


class CompatAsyncEngine:
    """Moteur SQLAlchemy 2.0 compatible async/sync."""

    def __init__(self, sync_engine: Engine) -> None:
        self.sync_engine = sync_engine
        self.dialect = sync_engine.dialect

    def connect(self) -> CompatAsyncConnection:
        return CompatAsyncConnection(self.sync_engine)

    def begin(self) -> CompatAsyncConnection:
        return CompatAsyncConnection(self.sync_engine)

    async def dispose(self) -> None:
        self.sync_engine.dispose()


class AsyncSession:
    """Session SQLAlchemy 2.0 exposant l'interface asynchrone complète sans requérir greenlet C-ext."""

    def __init__(self, sync_session: Session) -> None:
        self._session = sync_session

    async def __aenter__(self) -> "AsyncSession":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is not None:
            self._session.rollback()
        self._session.close()

    def add(self, instance: Any) -> None:
        self._session.add(instance)

    def add_all(self, instances: Any) -> None:
        self._session.add_all(instances)

    async def delete(self, instance: Any) -> None:
        self._session.delete(instance)

    async def scalar(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        return self._session.scalar(statement, *args, **kwargs)

    async def scalars(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        return self._session.scalars(statement, *args, **kwargs)

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        return self._session.execute(statement, *args, **kwargs)

    async def flush(self) -> None:
        self._session.flush()

    async def commit(self) -> None:
        self._session.commit()

    async def rollback(self) -> None:
        self._session.rollback()

    async def refresh(self, instance: Any) -> None:
        self._session.refresh(instance)

    async def close(self) -> None:
        self._session.close()


def build_async_engine(database_url: str | None = None) -> CompatAsyncEngine:
    settings = get_settings()
    raw_url = database_url or settings.DATABASE_URL
    sync_url = normalize_sync_db_url(raw_url)
    connect_args: dict[str, Any] = {}
    if sync_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    sync_engine = create_engine(sync_url, echo=False, future=True, connect_args=connect_args)
    return CompatAsyncEngine(sync_engine)


engine: CompatAsyncEngine = build_async_engine()
_SyncSessionLocal = sessionmaker(
    bind=engine.sync_engine,
    expire_on_commit=False,
    autoflush=False,
)


def AsyncSessionLocal() -> AsyncSession:
    return AsyncSession(_SyncSessionLocal())


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def check_database_health(custom_engine: CompatAsyncEngine | None = None) -> dict[str, Any]:
    target_engine = custom_engine or engine
    dialect_name = target_engine.dialect.name
    try:
        async with target_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "healthy", "dialect": dialect_name, "connected": True}
    except Exception as exc:
        return {
            "status": "unhealthy",
            "dialect": dialect_name,
            "connected": False,
            "detail": str(exc),
        }
