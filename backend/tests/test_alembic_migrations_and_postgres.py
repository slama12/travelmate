from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app.core.database import AsyncSession, build_async_engine
from app.core.seed import seed_initial_data
from app.models.entities import Accommodation, Destination, LocalTransport, Place, User

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI_PATH = BACKEND_ROOT / "alembic.ini"
MAX_ALEMBIC_VERSION_NUM_LEN = 32


def _make_alembic_config(db_url: str | None = None) -> Config:
    cfg = Config(str(ALEMBIC_INI_PATH))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    if db_url:
        cfg.attributes["sqlalchemy.url"] = db_url
    return cfg


def test_alembic_revision_ids_do_not_exceed_32_characters() -> None:
    """
    Vérifie qu'aucun identifiant de révision Alembic ne dépasse 32 caractères
    (limite VARCHAR(32) de la table alembic_version sous PostgreSQL) et que
    la chaîne 0001_initial_schema -> 0002_booking_geo -> 0003_planning_calendar est intègre.
    """
    cfg = _make_alembic_config()
    script_dir = ScriptDirectory.from_config(cfg)

    revisions = list(script_dir.walk_revisions())
    assert len(revisions) >= 3

    revision_ids: set[str] = set()
    for rev in revisions:
        assert isinstance(rev.revision, str) and rev.revision.strip(), (
            f"Identifiant de révision vide dans {rev.path}"
        )
        assert len(rev.revision) <= MAX_ALEMBIC_VERSION_NUM_LEN, (
            f"L'identifiant de révision '{rev.revision}' ({len(rev.revision)} caractères) "
            f"dépasse la limite PostgreSQL VARCHAR({MAX_ALEMBIC_VERSION_NUM_LEN}) de alembic_version.version_num !"
        )
        if isinstance(rev.down_revision, str):
            assert len(rev.down_revision) <= MAX_ALEMBIC_VERSION_NUM_LEN, (
                f"Le down_revision '{rev.down_revision}' dépasse {MAX_ALEMBIC_VERSION_NUM_LEN} caractères !"
            )
        filename = Path(rev.path).name
        assert filename.startswith(rev.revision), (
            f"Le fichier {filename} doit commencer par l'identifiant de révision '{rev.revision}'."
        )
        revision_ids.add(rev.revision)

    assert {
        "0001_initial_schema",
        "0002_booking_geo",
        "0003_planning_calendar",
        "0004_weather_ai_chat",
        "0005_step5a_budget_docs_rbac",
    }.issubset(revision_ids)
    assert script_dir.get_current_head() == "0005_step5a_budget_docs_rbac"


def _resolve_postgres_admin_and_test_urls() -> tuple[str, str, str, str]:
    """
    Résout l'hôte PostgreSQL actif (conteneur 'postgres' sous Docker ou 'localhost' depuis l'hôte)
    et retourne (admin_sync_url, test_sync_url, test_async_url, test_db_name).
    """
    pg_user = os.environ.get("POSTGRES_USER", "travelmate")
    pg_password = os.environ.get("POSTGRES_PASSWORD") or "travelmate_dev_password"
    pg_port = int(os.environ.get("POSTGRES_PORT", "5432"))
    test_db_name = "travelmate_test_migrations"

    candidate_hosts = []
    env_host = os.environ.get("POSTGRES_HOST")
    if env_host:
        candidate_hosts.append(env_host)
    for h in ("localhost", "127.0.0.1", "postgres"):
        if h not in candidate_hosts:
            candidate_hosts.append(h)

    last_err: Exception | None = None
    for host in candidate_hosts:
        admin_url = f"postgresql+psycopg://{pg_user}:{pg_password}@{host}:{pg_port}/postgres"
        try:
            eng = create_engine(admin_url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3})
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            eng.dispose()
            test_sync_url = (
                f"postgresql+psycopg://{pg_user}:{pg_password}@{host}:{pg_port}/{test_db_name}"
            )
            test_async_url = (
                f"postgresql+asyncpg://{pg_user}:{pg_password}@{host}:{pg_port}/{test_db_name}"
            )
            return admin_url, test_sync_url, test_async_url, test_db_name
        except Exception as exc:  # pragma: no cover - essai de l'hôte suivant
            last_err = exc

    pytest.fail(
        f"Impossible de joindre un vrai serveur PostgreSQL sur {candidate_hosts}:{pg_port} "
        f"pour le test d'intégration Alembic + Seed : {last_err}"
    )


@pytest.mark.asyncio
async def test_postgres_alembic_upgrade_head_from_empty_db_and_idempotent_seed() -> None:
    """
    Test d'intégration sur un VRAI PostgreSQL (pas SQLite) :
    1. Crée une base PostgreSQL totalement vide.
    2. Exécute 'alembic upgrade head' (0001 -> 0002 -> 0003 -> 0004 -> 0005) et vérifie alembic_version.
    3. Exécute le seed initial une 1re fois et vérifie les données insérées.
    4. Exécute le seed une 2de fois et vérifie qu'il est strictement idempotent.
    """
    try:
        import psycopg  # noqa: F401
    except ModuleNotFoundError:
        import subprocess

        repo_root = Path(__file__).resolve().parents[2]
        res = subprocess.run(
            [
                "wsl",
                "docker",
                "compose",
                "exec",
                "-T",
                "-e",
                "POSTGRES_HOST=postgres",
                "backend",
                "pytest",
                "tests/test_alembic_migrations_and_postgres.py::test_postgres_alembic_upgrade_head_from_empty_db_and_idempotent_seed",
                "-v",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert res.returncode == 0, f"Échec du test PostgreSQL dans le conteneur backend :\n{res.stdout}\n{res.stderr}"
        return

    admin_sync_url, test_sync_url, test_async_url, test_db_name = (
        _resolve_postgres_admin_and_test_urls()
    )

    admin_engine = create_engine(admin_sync_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        assert conn.dialect.name == "postgresql"
        conn.execute(text(f"DROP DATABASE IF EXISTS {test_db_name} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {test_db_name}"))
    admin_engine.dispose()

    try:
        # 1. Exécute `alembic upgrade head` depuis la base PostgreSQL vide
        alembic_cfg = _make_alembic_config(db_url=test_sync_url)
        command.upgrade(alembic_cfg, "head")

        # Vérifie sur PostgreSQL que alembic_version contient bien '0005_step5a_budget_docs_rbac'
        # dans une colonne VARCHAR(32) et que les nouvelles colonnes des étapes 4 et 5A existent
        verify_engine = create_engine(test_sync_url)
        with verify_engine.connect() as conn:
            assert conn.dialect.name == "postgresql"
            version_num = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert version_num == "0005_step5a_budget_docs_rbac"
            assert len(version_num) <= MAX_ALEMBIC_VERSION_NUM_LEN

            col_max_len = conn.execute(
                text(
                    "SELECT character_maximum_length "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'alembic_version' AND column_name = 'version_num'"
                )
            ).scalar_one()
            assert col_max_len == 32

            step4_itinerary_cols = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'itinerary_items'"
                    )
                ).fetchall()
            }
            assert {"transit_time_source", "weather_dismissed"}.issubset(step4_itinerary_cols)

            step4_chat_cols = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'chat_messages'"
                    )
                ).fetchall()
            }
            assert {"proposed_action", "action_status"}.issubset(step4_chat_cols)

            chat_unrec_cols = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'chat_unrecognized'"
                    )
                ).fetchall()
            }
            assert {
                "id",
                "trip_id",
                "user_id",
                "raw_message",
                "reason",
                "assistant_reply",
                "created_at",
            }.issubset(chat_unrec_cols)

            step5a_vault_cols = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'vault_documents'"
                    )
                ).fetchall()
            }
            assert {"owner_id", "is_shared", "expires_on"}.issubset(step5a_vault_cols)
        verify_engine.dispose()

        # 2. Exécute le seed une 1re fois puis une 2de fois sur PostgreSQL et vérifie l'idempotence
        pg_async_engine = build_async_engine(test_async_url)
        assert pg_async_engine.dialect.name == "postgresql"
        sync_session_maker = sessionmaker(
            bind=pg_async_engine.sync_engine,
            expire_on_commit=False,
            autoflush=False,
        )

        async with AsyncSession(sync_session_maker()) as session:
            first_stats = await seed_initial_data(session)
            assert first_stats["destinations_created"] == 5
            assert first_stats["places_created"] > 0
            assert first_stats["accommodations_created"] > 0

            dest_count_1 = await session.scalar(select(func.count()).select_from(Destination))
            place_count_1 = await session.scalar(select(func.count()).select_from(Place))
            acc_count_1 = await session.scalar(select(func.count()).select_from(Accommodation))
            tr_count_1 = await session.scalar(select(func.count()).select_from(LocalTransport))
            user_count_1 = await session.scalar(select(func.count()).select_from(User))

            assert dest_count_1 == 5
            assert place_count_1 == first_stats["places_created"]
            assert acc_count_1 == first_stats["accommodations_created"]
            assert tr_count_1 and tr_count_1 > 0
            assert user_count_1 == 1

        # Second lancement : aucune donnée ne doit être recréée ni dupliquée
        async with AsyncSession(sync_session_maker()) as session:
            second_stats = await seed_initial_data(session)
            assert second_stats == {
                "destinations_created": 0,
                "places_created": 0,
                "accommodations_created": 0,
            }

            dest_count_2 = await session.scalar(select(func.count()).select_from(Destination))
            place_count_2 = await session.scalar(select(func.count()).select_from(Place))
            acc_count_2 = await session.scalar(select(func.count()).select_from(Accommodation))
            tr_count_2 = await session.scalar(select(func.count()).select_from(LocalTransport))
            user_count_2 = await session.scalar(select(func.count()).select_from(User))

            assert dest_count_2 == dest_count_1
            assert place_count_2 == place_count_1
            assert acc_count_2 == acc_count_1
            assert tr_count_2 == tr_count_1
            assert user_count_2 == user_count_1

        await pg_async_engine.dispose()
    finally:
        cleanup_engine = create_engine(admin_sync_url, isolation_level="AUTOCOMMIT")
        with cleanup_engine.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {test_db_name} WITH (FORCE)"))
        cleanup_engine.dispose()
