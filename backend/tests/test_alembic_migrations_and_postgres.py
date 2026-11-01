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
        "0006_world_cities_geonames",
        "0007_world_places_step2",
        "0008_place_photos_step3",
        "0009_multi_city_stages_step1",
    }.issubset(revision_ids)
    assert script_dir.get_heads() == ["0009_multi_city_stages_step1"]
    assert script_dir.get_current_head() == "0009_multi_city_stages_step1"


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
    2. Exécute 'alembic upgrade head' (0001 -> ... -> 0009) et vérifie alembic_version.
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

        # Vérifie sur PostgreSQL que alembic_version contient bien '0009_multi_city_stages_step1'
        # dans une colonne VARCHAR(32) et que les nouvelles colonnes existent
        verify_engine = create_engine(test_sync_url)
        with verify_engine.connect() as conn:
            assert conn.dialect.name == "postgresql"
            version_num = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert version_num == "0009_multi_city_stages_step1"
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
            assert {"transit_time_source", "weather_dismissed", "stage_id"}.issubset(step4_itinerary_cols)

            trip_stages_cols = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'trip_stages'"
                    )
                ).fetchall()
            }
            assert {
                "id",
                "trip_id",
                "destination_id",
                "order_index",
                "geoname_id",
                "city_name",
                "country_name",
                "country_code_iso2",
                "timezone",
                "arrival_date",
                "departure_date",
                "nights",
                "arrival_at",
                "departure_at",
                "arrival_transport_mode",
                "transport_unlocked",
            }.issubset(trip_stages_cols)

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

            dest_cols = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'destinations'"
                    )
                ).fetchall()
            }
            assert {"geoname_id", "population"}.issubset(dest_cols)

            places_cols = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'places'"
                    )
                ).fetchall()
            }
            assert {
                "source_provider",
                "external_place_id",
                "address",
                "website_url",
                "price_label",
                "hours_status",
                "source_url",
                "source_attribution",
                "notoriety_score",
                "photo_file_title",
                "photo_author",
                "photo_license",
                "photo_commons_url",
                "photo_source",
                "photo_checked_at",
            }.issubset(places_cols)
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


def test_postgres_alembic_upgrade_0008_to_0009_migrates_existing_trips() -> None:
    """
    Teste la migration Alembic 0009_multi_city_stages_step1 sur une base PostgreSQL
    contenant déjà des séjours (trips), réservations, visites et dépenses à l'étape 0008 :
    chaque séjour existant doit être automatiquement rattaché à un voyage d'une seule étape (order_index=1)
    avec ses dates, nuits, fuseau horaire et éléments enfants rattachés.
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
                "tests/test_alembic_migrations_and_postgres.py::test_postgres_alembic_upgrade_0008_to_0009_migrates_existing_trips",
                "-v",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert res.returncode == 0, f"Échec du test PostgreSQL dans le conteneur backend :\n{res.stdout}\n{res.stderr}"
        return

    admin_sync_url, test_sync_url, _test_async_url, test_db_name = (
        _resolve_postgres_admin_and_test_urls()
    )

    admin_engine = create_engine(admin_sync_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {test_db_name} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {test_db_name}"))
    admin_engine.dispose()

    try:
        alembic_cfg = _make_alembic_config(db_url=test_sync_url)
        # 1. Monte la base jusqu'à 0008_place_photos_step3 (avant le multi-villes)
        command.upgrade(alembic_cfg, "0008_place_photos_step3")

        verify_engine = create_engine(test_sync_url)
        with verify_engine.begin() as conn:
            v8 = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert v8 == "0008_place_photos_step3"

            # Insère un utilisateur, 2 destinations et 2 séjours existants avant la migration 0009
            conn.execute(
                text(
                    "INSERT INTO users (id, email, full_name, password_hash, preferred_style, created_at) "
                    "VALUES ('u-mig-1', 'mig@travelmate.fr', 'Voyageur Migration', 'hash', 'STANDARD', NOW())"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO destinations (id, geoname_id, city_name, country_name, country_code_iso2, "
                    "iata_code, timezone, latitude, longitude, population, hero_image_url, description, "
                    "practical_info, useful_phrases) "
                    "VALUES "
                    "('d-mig-paris', 2988507, 'Paris', 'France', 'FR', 'CDG', 'Europe/Paris', 48.8566, 2.3522, "
                    "2138551, 'https://commons.wikimedia.org/p.jpg', 'Paris', '{}'::json, '[]'::json), "
                    "('d-mig-tokyo', 1850147, 'Tokyo', 'Japon', 'JP', 'HND', 'Asia/Tokyo', 35.6762, 139.6503, "
                    "13960000, 'https://commons.wikimedia.org/t.jpg', 'Tokyo', '{}'::json, '[]'::json)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO places (id, destination_id, name, category, description, latitude, longitude, "
                    "opening_hours, recommended_duration_min, avg_rating, estimated_cost, is_outdoor, "
                    "price_tier, hero_photos, source_provider, notoriety_score) "
                    "VALUES ('p-mig-louvre', 'd-mig-paris', 'Musée du Louvre', 'CULTURE', 'Musée', 48.8606, 2.3376, "
                    "'{}'::json, 120, 4.9, 22.0, false, 'STANDARD', '[]'::json, 'wikidata', 100)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO trips (id, owner_id, destination_id, title, arrival_at, departure_at, "
                    "travel_style, total_budget_planned, currency, preferences, selected_place_ids, status, created_at) "
                    "VALUES "
                    "('t-mig-1', 'u-mig-1', 'd-mig-paris', 'Séjour Paris', '2026-06-10 09:00:00+00', '2026-06-14 18:00:00+00', "
                    "'CULTURE', 1500.0, 'EUR', '{}'::json, '[\"p-mig-louvre\"]'::json, 'ACTIVE', NOW()), "
                    "('t-mig-2', 'u-mig-1', 'd-mig-tokyo', 'Séjour Tokyo', '2026-09-01 03:00:00+00', '2026-09-06 10:00:00+00', "
                    "'MIXED', 2800.0, 'EUR', '{}'::json, '[]'::json, 'DRAFT', NOW())"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO flight_bookings (id, trip_id, idempotency_key, pnr_reference, airline, "
                    "flight_number_outbound, flight_number_inbound, origin_iata, destination_iata, "
                    "departure_outbound_at, arrival_outbound_at, departure_inbound_at, arrival_inbound_at, "
                    "price, currency, cabin_class, flight_status, gmail_confirmation_sent, gmail_send_status, "
                    "gmail_send_attempts, confirmation_email_preview) "
                    "VALUES ('fb-mig-1', 't-mig-1', 'idem-mig-1', 'TM-MIG01', 'Air France', 'AF7651', 'AF7658', "
                    "'LYS', 'CDG', '2026-06-10 07:30:00+00', '2026-06-10 09:00:00+00', '2026-06-14 18:00:00+00', "
                    "'2026-06-14 19:30:00+00', 180.0, 'EUR', 'ECONOMY', 'SCHEDULED', false, 'PENDING', 0, '{}'::json)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO itinerary_items (id, trip_id, place_id, visit_date, start_at, end_at, "
                    "duration_minutes, day_order_index, transit_mode_to_next, transit_duration_to_next_min, "
                    "transit_distance_meters, transit_time_source, weather_warning, weather_dismissed, "
                    "calendar_sync_status, calendar_sync_attempts) "
                    "VALUES ('it-mig-1', 't-mig-1', 'p-mig-louvre', '2026-06-11', '2026-06-11 08:00:00+00', "
                    "'2026-06-11 10:00:00+00', 120, 1, 'METRO', 0, 0, 'ESTIMATED', false, false, 'SYNCED', 1)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO budget_items (id, trip_id, category, title, planned_amount, actual_amount, "
                    "currency, incurred_at) "
                    "VALUES ('bi-mig-1', 't-mig-1', 'FLIGHT', 'Vol LYS-CDG', 180.0, 180.0, 'EUR', NOW())"
                )
            )

        # 2. Applique la migration 0009_multi_city_stages_step1 sur la base contenant ces séjours
        command.upgrade(alembic_cfg, "head")

        with verify_engine.connect() as conn:
            v9 = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert v9 == "0009_multi_city_stages_step1"

            stage_rows = conn.execute(
                text(
                    "SELECT id, trip_id, destination_id, order_index, city_name, country_name, timezone, "
                    "arrival_date, departure_date, nights, arrival_transport_mode, transport_unlocked "
                    "FROM trip_stages ORDER BY trip_id"
                )
            ).mappings().all()
            assert len(stage_rows) == 2

            st_by_trip = {r["trip_id"]: r for r in stage_rows}
            st1 = st_by_trip["t-mig-1"]
            assert st1["order_index"] == 1
            assert st1["city_name"] == "Paris"
            assert st1["country_name"] == "France"
            assert st1["timezone"] == "Europe/Paris"
            assert str(st1["arrival_date"]) == "2026-06-10"
            assert str(st1["departure_date"]) == "2026-06-14"
            assert st1["nights"] == 4
            assert st1["arrival_transport_mode"] == "VOL"
            assert st1["transport_unlocked"] is True

            st2 = st_by_trip["t-mig-2"]
            assert st2["order_index"] == 1
            assert st2["city_name"] == "Tokyo"
            assert st2["country_name"] == "Japon"
            assert st2["timezone"] == "Asia/Tokyo"
            assert str(st2["arrival_date"]) == "2026-09-01"
            assert str(st2["departure_date"]) == "2026-09-06"
            assert st2["nights"] == 5
            assert st2["arrival_transport_mode"] == "VOL"
            assert st2["transport_unlocked"] is False

            # Vérifie que le vol, la visite et la dépense de t-mig-1 ont bien été rattachés à son étape
            fb_stage_id = conn.execute(
                text("SELECT stage_id FROM flight_bookings WHERE id = 'fb-mig-1'")
            ).scalar_one()
            it_stage_id = conn.execute(
                text("SELECT stage_id FROM itinerary_items WHERE id = 'it-mig-1'")
            ).scalar_one()
            bi_stage_id = conn.execute(
                text("SELECT stage_id FROM budget_items WHERE id = 'bi-mig-1'")
            ).scalar_one()
            assert fb_stage_id == st1["id"]
            assert it_stage_id == st1["id"]
            assert bi_stage_id == st1["id"]
        verify_engine.dispose()
    finally:
        cleanup_engine = create_engine(admin_sync_url, isolation_level="AUTOCOMMIT")
        with cleanup_engine.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {test_db_name} WITH (FORCE)"))
        cleanup_engine.dispose()

