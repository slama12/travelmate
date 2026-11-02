from collections.abc import AsyncGenerator

from httpx import ASGITransport, AsyncClient
import pytest

from app.core.config import get_settings
from app.core.database import AsyncSession, AsyncSessionLocal, get_db, rebind_database_engine
from app.core.providers import reset_provider_registry
from app.core.seed import seed_initial_data
from app.main import app
from tests.test_db_lifecycle import (
    TEST_DB_NAME,
    reset_travelmate_test_state_sync,
    setup_travelmate_test_database,
)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: test d'intégration contre les vraies API externes (non bloquant).",
    )


@pytest.fixture(autouse=True)
def default_simulated_ai_provider_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Par défaut, les tests unitaires/d'intégration s'exécutent en mode simulé déterministe
    sur la base 'travelmate_test' (jamais sur 'travelmate_db').
    """
    test_sync_url, test_async_url, dev_sync_url = setup_travelmate_test_database()
    monkeypatch.setenv("POSTGRES_DB", TEST_DB_NAME)
    monkeypatch.setenv("DATABASE_URL", test_async_url)
    monkeypatch.setenv("DATABASE_URL_SYNC", test_sync_url)
    monkeypatch.setenv("DEV_DATABASE_URL_SYNC", dev_sync_url)
    monkeypatch.setenv("AI_CHAT_STRATEGY", "rules")
    monkeypatch.setenv("AI_PROVIDER_MODE", "simulated")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "mistral")
    get_settings.cache_clear()
    reset_provider_registry()
    rebind_database_engine(test_async_url)


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    reset_travelmate_test_state_sync()
    async with AsyncSessionLocal() as session:
        await seed_initial_data(session)
        yield session


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()
