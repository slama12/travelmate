import pytest

from tests.test_db_lifecycle import (
    setup_travelmate_test_database,
    teardown_travelmate_test_database,
)


def pytest_sessionstart(session: pytest.Session) -> None:
    """
    Au début de la session de test :
    - Crée la base dédiée 'travelmate_test'
    - Applique les migrations Alembic ('alembic upgrade head')
    - Démarre le serveur Uvicorn de test branché sur 'travelmate_test'
    """
    setup_travelmate_test_database()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """
    À la fin de la session de test :
    - Arrête le serveur Uvicorn de test
    - Détruit la base dédiée 'travelmate_test'
    """
    teardown_travelmate_test_database()
