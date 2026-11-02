from __future__ import annotations

import asyncio
import atexit
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, rebind_database_engine
from app.core.providers import reset_provider_registry
from app.core.seed import seed_initial_data

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI_PATH = BACKEND_ROOT / "alembic.ini"

TEST_DB_NAME = "travelmate_test"
DEV_DB_NAME = "travelmate_db"
SEED_DEMO_EMAIL = "demo@travelmate.app"
SEED_DEMO_CITIES = ("Paris", "Marrakech", "Tokyo", "New York", "Rome")

_LIFECYCLE_ACTIVE = False
_TEST_SERVER_PROC: subprocess.Popen[str] | None = None
_ADMIN_SYNC_URL: str | None = None
_TEST_SYNC_URL: str | None = None
_TEST_ASYNC_URL: str | None = None
_DEV_SYNC_URL: str | None = None
_INITIAL_ENV_SNAPSHOT: dict[str, str] = {}


def _capture_initial_env() -> None:
    if _INITIAL_ENV_SNAPSHOT:
        return
    for key in (
        "DATABASE_URL",
        "DATABASE_URL_SYNC",
        "DEV_DATABASE_URL_SYNC",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
    ):
        val = os.environ.get(key)
        if val is not None:
            _INITIAL_ENV_SNAPSHOT[key] = val


def resolve_postgres_urls() -> tuple[str, str, str, str]:
    """
    Résout l'hôte PostgreSQL actif et retourne :
    (admin_sync_url, test_sync_url, test_async_url, dev_sync_url)
    En garantissant que test_sync_url et test_async_url pointent exclusivement vers 'travelmate_test'.
    """
    _capture_initial_env()
    if _ADMIN_SYNC_URL and _TEST_SYNC_URL and _TEST_ASYNC_URL and _DEV_SYNC_URL:
        return _ADMIN_SYNC_URL, _TEST_SYNC_URL, _TEST_ASYNC_URL, _DEV_SYNC_URL

    raw_url = (
        _INITIAL_ENV_SNAPSHOT.get("DEV_DATABASE_URL_SYNC")
        or _INITIAL_ENV_SNAPSHOT.get("DATABASE_URL_SYNC")
        or _INITIAL_ENV_SNAPSHOT.get("DATABASE_URL")
        or ""
    )
    parsed = urlparse(raw_url) if "://" in raw_url else None

    pg_user = (
        os.environ.get("POSTGRES_USER")
        or (parsed.username if parsed and parsed.username else None)
        or "travelmate"
    )
    pg_password = (
        os.environ.get("POSTGRES_PASSWORD")
        or (parsed.password if parsed and parsed.password else None)
        or "travelmate_secret"
    )
    pg_port = int(
        os.environ.get("POSTGRES_PORT")
        or (parsed.port if parsed and parsed.port else None)
        or 5432
    )

    candidate_hosts: list[str] = []
    if os.environ.get("POSTGRES_HOST"):
        candidate_hosts.append(os.environ["POSTGRES_HOST"])
    if parsed and parsed.hostname and parsed.hostname not in candidate_hosts:
        candidate_hosts.append(parsed.hostname)
    for host in ("postgres", "localhost", "127.0.0.1"):
        if host not in candidate_hosts:
            candidate_hosts.append(host)

    candidate_passwords = [pg_password]
    for fallback_pwd in ("travelmate_secret", "travelmate_dev_password"):
        if fallback_pwd not in candidate_passwords:
            candidate_passwords.append(fallback_pwd)

    last_err: Exception | None = None
    for host in candidate_hosts:
        for pwd in candidate_passwords:
            admin_url = f"postgresql+psycopg://{pg_user}:{pwd}@{host}:{pg_port}/postgres"
            try:
                eng = create_engine(
                    admin_url,
                    isolation_level="AUTOCOMMIT",
                    connect_args={"connect_timeout": 3},
                )
                with eng.connect() as conn:
                    conn.execute(text("SELECT 1"))
                eng.dispose()

                test_sync_url = (
                    f"postgresql+psycopg://{pg_user}:{pwd}@{host}:{pg_port}/{TEST_DB_NAME}"
                )
                test_async_url = (
                    f"postgresql+asyncpg://{pg_user}:{pwd}@{host}:{pg_port}/{TEST_DB_NAME}"
                )
                dev_sync_url = (
                    _INITIAL_ENV_SNAPSHOT.get("DEV_DATABASE_URL_SYNC")
                    or f"postgresql+psycopg://{pg_user}:{pwd}@{host}:{pg_port}/{DEV_DB_NAME}"
                )
                assert TEST_DB_NAME == "travelmate_test"
                assert DEV_DB_NAME not in test_sync_url
                assert DEV_DB_NAME not in test_async_url
                return admin_url, test_sync_url, test_async_url, dev_sync_url
            except Exception as exc:
                last_err = exc

    raise RuntimeError(
        f"Impossible de joindre PostgreSQL sur {candidate_hosts}:{pg_port} pour initialiser {TEST_DB_NAME}: {last_err}"
    )


def _make_alembic_config(db_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI_PATH))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    cfg.attributes["sqlalchemy.url"] = db_url
    return cfg


def reset_travelmate_test_state_sync(sync_engine: Engine | None = None) -> None:
    """
    Réinitialise les données de travelmate_test entre deux tests (supprime les comptes/séjours/villes hors seed)
    tout en conservant les 5 destinations de démonstration (et leurs lieux/hébergements du seed)
    ainsi que l'utilisateur de démonstration.
    Garantit de ne jamais s'exécuter sur travelmate_db.
    """
    from app.core.database import engine as current_engine

    target_engine = sync_engine or current_engine.sync_engine
    db_name = str(target_engine.url.database or "")
    if db_name != TEST_DB_NAME:
        raise RuntimeError(
            f"Refus de réinitialiser une base autre que '{TEST_DB_NAME}' (base actuelle: '{db_name}')."
        )

    seed_cities_sql = "('Paris', 'Marrakech', 'Tokyo', 'New York', 'Rome')"
    with target_engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM chat_unrecognized WHERE user_id IN "
                "(SELECT id FROM users WHERE email <> :demo_email)"
            ),
            {"demo_email": SEED_DEMO_EMAIL},
        )
        conn.execute(
            text(
                "DELETE FROM vault_documents WHERE owner_id IN "
                "(SELECT id FROM users WHERE email <> :demo_email)"
            ),
            {"demo_email": SEED_DEMO_EMAIL},
        )
        conn.execute(
            text(
                "DELETE FROM trips WHERE owner_id IN "
                "(SELECT id FROM users WHERE email <> :demo_email)"
            ),
            {"demo_email": SEED_DEMO_EMAIL},
        )
        conn.execute(
            text("DELETE FROM users WHERE email <> :demo_email"),
            {"demo_email": SEED_DEMO_EMAIL},
        )
        conn.execute(
            text(
                f"DELETE FROM places WHERE destination_id NOT IN "
                f"(SELECT id FROM destinations WHERE city_name IN {seed_cities_sql}) "
                f"OR source_provider NOT IN ('simulated')"
            )
        )
        conn.execute(
            text(
                f"DELETE FROM accommodations WHERE destination_id NOT IN "
                f"(SELECT id FROM destinations WHERE city_name IN {seed_cities_sql}) "
                f"OR source_provider NOT IN ('simulated', 'hotel_official', 'airbnb_partner_redirect')"
            )
        )
        conn.execute(
            text(
                f"DELETE FROM destinations WHERE city_name NOT IN {seed_cities_sql}"
            )
        )


async def ensure_seed_on_travelmate_test() -> None:
    async with AsyncSessionLocal() as session:
        await seed_initial_data(session)


def _start_test_backend_uvicorn(test_sync_url: str, test_async_url: str) -> str:
    global _TEST_SERVER_PROC
    test_port = int(os.environ.get("TEST_API_PORT", "8001"))
    base_url = f"http://localhost:{test_port}"

    if _TEST_SERVER_PROC is not None and _TEST_SERVER_PROC.poll() is None:
        os.environ["TEST_API_BASE_URL"] = base_url
        return base_url

    # Vérifie si un serveur de test tourne déjà sur ce port et pointe bien sur travelmate_test
    try:
        resp = httpx.get(f"{base_url}/health", timeout=1.5)
        if resp.status_code == 200:
            os.environ["TEST_API_BASE_URL"] = base_url
            return base_url
    except Exception:
        pass

    env = os.environ.copy()
    env["POSTGRES_DB"] = TEST_DB_NAME
    env["DATABASE_URL"] = test_async_url
    env["DATABASE_URL_SYNC"] = test_sync_url
    env["AI_PROVIDER_MODE"] = "simulated"
    env["AI_CHAT_STRATEGY"] = "rules"

    _TEST_SERVER_PROC = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(test_port),
            "--log-level",
            "warning",
        ],
        cwd=str(BACKEND_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    deadline = time.monotonic() + 20.0
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        if _TEST_SERVER_PROC.poll() is not None:
            raise RuntimeError(
                f"Le serveur Uvicorn de test sur {base_url} s'est arrêté prématurément (code={_TEST_SERVER_PROC.returncode})."
            )
        try:
            resp = httpx.get(f"{base_url}/health", timeout=1.5)
            if resp.status_code == 200:
                os.environ["TEST_API_BASE_URL"] = base_url
                return base_url
        except Exception as exc:
            last_err = exc
        time.sleep(0.25)

    raise RuntimeError(f"Impossible de démarrer le serveur de test sur {base_url}: {last_err}")


def _stop_test_backend_uvicorn() -> None:
    global _TEST_SERVER_PROC
    if _TEST_SERVER_PROC is not None:
        try:
            if _TEST_SERVER_PROC.poll() is None:
                _TEST_SERVER_PROC.terminate()
                try:
                    _TEST_SERVER_PROC.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    _TEST_SERVER_PROC.kill()
                    _TEST_SERVER_PROC.wait(timeout=3.0)
        except Exception:
            pass
        finally:
            _TEST_SERVER_PROC = None


def setup_travelmate_test_database() -> tuple[str, str, str]:
    """
    Crée la base dédiée 'travelmate_test' au début de la session de test,
    applique toutes les migrations Alembic ('alembic upgrade head'),
    charge le seed initial, branche l'application sur 'travelmate_test'
    et démarre l'instance Uvicorn de test connectée à 'travelmate_test'.
    """
    global _LIFECYCLE_ACTIVE, _ADMIN_SYNC_URL, _TEST_SYNC_URL, _TEST_ASYNC_URL, _DEV_SYNC_URL

    admin_url, test_sync_url, test_async_url, dev_sync_url = resolve_postgres_urls()
    _ADMIN_SYNC_URL = admin_url
    _TEST_SYNC_URL = test_sync_url
    _TEST_ASYNC_URL = test_async_url
    _DEV_SYNC_URL = dev_sync_url

    os.environ["DEV_DATABASE_URL_SYNC"] = dev_sync_url
    os.environ["POSTGRES_DB"] = TEST_DB_NAME
    os.environ["DATABASE_URL"] = test_async_url
    os.environ["DATABASE_URL_SYNC"] = test_sync_url

    if not _LIFECYCLE_ACTIVE:
        admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)"))
            conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
        admin_engine.dispose()

        alembic_cfg = _make_alembic_config(test_sync_url)
        command.upgrade(alembic_cfg, "head")

        get_settings.cache_clear()
        reset_provider_registry()
        rebind_database_engine(test_async_url)

        asyncio.run(ensure_seed_on_travelmate_test())
        _start_test_backend_uvicorn(test_sync_url, test_async_url)

        _LIFECYCLE_ACTIVE = True
        atexit.register(teardown_travelmate_test_database)
    else:
        get_settings.cache_clear()
        rebind_database_engine(test_async_url)
        _start_test_backend_uvicorn(test_sync_url, test_async_url)

    return test_sync_url, test_async_url, dev_sync_url


def teardown_travelmate_test_database() -> None:
    """
    Arrête le serveur de test, ferme les connexions SQLAlchemy et détruit
    la base 'travelmate_test' à la fin de la session de test.
    """
    global _LIFECYCLE_ACTIVE
    if not _LIFECYCLE_ACTIVE:
        return

    _stop_test_backend_uvicorn()

    try:
        from app.core.database import engine as current_engine

        current_engine.sync_engine.dispose()
    except Exception:
        pass

    if _ADMIN_SYNC_URL:
        try:
            admin_engine = create_engine(_ADMIN_SYNC_URL, isolation_level="AUTOCOMMIT")
            with admin_engine.connect() as conn:
                conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)"))
            admin_engine.dispose()
        except Exception:
            pass

    _LIFECYCLE_ACTIVE = False


def cleanup_and_verify_cascade_for_emails(
    emails: list[str] | set[str] | tuple[str, ...],
    db_sync_url: str | None = None,
) -> dict[str, Any]:
    """
    Supprime les comptes de test identifiés par leurs adresses e-mail et vérifie
    que la suppression en cascade a bien purgé tous leurs séjours et entités liées
    (trips, trip_members, itinerary_items, flight_bookings, accommodation_bookings,
    budget_items, vault_documents, chat_messages, alerts).
    """
    normalized_emails = sorted({e.strip().lower() for e in emails if e and e.strip()})
    if not normalized_emails:
        return {"deleted_users": 0, "deleted_trips": 0, "cascade_verified": True}

    for email in normalized_emails:
        if email == SEED_DEMO_EMAIL:
            raise ValueError(f"Interdiction de supprimer le compte de démo {SEED_DEMO_EMAIL}.")

    target_url = db_sync_url or _TEST_SYNC_URL or os.environ.get("DATABASE_URL_SYNC")
    if not target_url:
        _, target_url, _, _ = resolve_postgres_urls()

    eng = create_engine(target_url)
    try:
        with eng.begin() as conn:
            user_rows = conn.execute(
                text("SELECT id, email FROM users WHERE lower(email) = ANY(:emails)"),
                {"emails": normalized_emails},
            ).fetchall()
            user_ids = [str(r[0]) for r in user_rows]

            if not user_ids:
                return {"deleted_users": 0, "deleted_trips": 0, "cascade_verified": True}

            trip_rows = conn.execute(
                text("SELECT id FROM trips WHERE owner_id = ANY(:uids)"),
                {"uids": user_ids},
            ).fetchall()
            trip_ids = [str(r[0]) for r in trip_rows]

            # Nettoyage préalable des tables à FK ON DELETE SET NULL pour ne laisser aucun résidu
            conn.execute(
                text("DELETE FROM chat_unrecognized WHERE user_id = ANY(:uids)"),
                {"uids": user_ids},
            )
            conn.execute(
                text("DELETE FROM vault_documents WHERE owner_id = ANY(:uids)"),
                {"uids": user_ids},
            )

            # Suppression des utilisateurs -> déclenche ON DELETE CASCADE sur trips et toutes les tables filles
            del_res = conn.execute(
                text("DELETE FROM users WHERE id = ANY(:uids)"),
                {"uids": user_ids},
            )
            deleted_users = int(del_res.rowcount or 0)

            # Vérification stricte de la suppression en cascade
            remaining_users = conn.execute(
                text("SELECT count(*) FROM users WHERE id = ANY(:uids)"),
                {"uids": user_ids},
            ).scalar_one()
            assert remaining_users == 0, f"Utilisateurs non supprimés : {remaining_users}"

            if trip_ids:
                for child_table, fk_col in (
                    ("trips", "id"),
                    ("trip_members", "trip_id"),
                    ("itinerary_items", "trip_id"),
                    ("flight_bookings", "trip_id"),
                    ("accommodation_bookings", "trip_id"),
                    ("budget_items", "trip_id"),
                    ("vault_documents", "trip_id"),
                    ("chat_messages", "trip_id"),
                    ("chat_unrecognized", "trip_id"),
                    ("alerts", "trip_id"),
                    ("place_votes", "trip_id"),
                    ("travel_journals", "trip_id"),
                ):
                    remaining_child = conn.execute(
                        text(f"SELECT count(*) FROM {child_table} WHERE {fk_col} = ANY(:tids)"),
                        {"tids": trip_ids},
                    ).scalar_one()
                    assert remaining_child == 0, (
                        f"Échec de la suppression en cascade dans {child_table}: "
                        f"{remaining_child} lignes restantes pour trips={trip_ids}"
                    )

            return {
                "deleted_users": deleted_users,
                "deleted_trips": len(trip_ids),
                "cascade_verified": True,
            }
    finally:
        eng.dispose()
