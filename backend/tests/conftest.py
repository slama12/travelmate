from collections.abc import AsyncGenerator

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy.orm import sessionmaker

from app.core.database import AsyncSession, Base, build_async_engine, get_db
from app.core.seed import seed_initial_data
from app.main import app


@pytest.fixture
async def db_session(tmp_path) -> AsyncGenerator[AsyncSession, None]:
    db_file = tmp_path / "test_travelmate.db"
    test_engine = build_async_engine(f"sqlite:///{db_file}")
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sync_session_maker = sessionmaker(
        bind=test_engine.sync_engine,
        expire_on_commit=False,
        autoflush=False,
    )
    async with AsyncSession(sync_session_maker()) as session:
        await seed_initial_data(session)
        yield session

    await test_engine.dispose()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()
