from __future__ import annotations

import os
import uuid

from httpx import AsyncClient
import pytest
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.core.database import engine
from tests.test_db_lifecycle import (
    DEV_DB_NAME,
    TEST_DB_NAME,
    cleanup_and_verify_cascade_for_emails,
    setup_travelmate_test_database,
)


@pytest.mark.asyncio
async def test_test_service_points_exclusively_to_travelmate_test_with_migrations_applied() -> None:
    """
    Vérifie que la session de test cible exclusivement la base dédiée 'travelmate_test'
    (jamais 'travelmate_db') et que les migrations Alembic y sont appliquées.
    """
    test_sync_url, test_async_url, _ = setup_travelmate_test_database()
    settings = get_settings()

    assert os.environ.get("POSTGRES_DB") == TEST_DB_NAME
    assert TEST_DB_NAME in settings.DATABASE_URL
    assert DEV_DB_NAME not in settings.DATABASE_URL
    assert str(engine.sync_engine.url.database) == TEST_DB_NAME
    assert str(engine.sync_engine.url.database) != DEV_DB_NAME

    eng = create_engine(test_sync_url)
    try:
        with eng.connect() as conn:
            current_db = conn.execute(text("SELECT current_database()")).scalar_one()
            assert current_db == TEST_DB_NAME
            alembic_rev = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert alembic_rev == "0009_multi_city_stages_step1"
    finally:
        eng.dispose()


@pytest.mark.asyncio
async def test_playwright_account_and_trip_cascade_deletion_verified(
    client: AsyncClient,
) -> None:
    """
    Vérifie que le nettoyage d'un compte 'playwright.*' supprime en cascade
    ses séjours et toutes les lignes liées (trip_members, flight_bookings,
    itinerary_items, budget_items, chat_messages).
    """
    test_sync_url, _, _ = setup_travelmate_test_database()
    email = f"playwright.cascade.{uuid.uuid4().hex[:8]}@travelmate.app"

    reg = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "CascadePassword2026!",
            "full_name": "Test Cascade Playwright",
            "preferred_style": "STANDARD",
        },
    )
    assert reg.status_code == 201
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    dests = (await client.get("/api/v1/destinations")).json()
    paris = next(d for d in dests if d["city_name"] == "Paris")

    trip_resp = await client.post(
        "/api/v1/trips",
        headers=headers,
        json={
            "destination_id": paris["id"],
            "title": "Séjour Cascade Test",
            "travel_style": "STANDARD",
            "total_budget_planned": "1500.00",
            "currency": "EUR",
        },
    )
    assert trip_resp.status_code == 201
    trip_id = trip_resp.json()["id"]

    book_resp = await client.post(
        "/api/v1/flights/book",
        headers=headers,
        json={
            "trip_id": trip_id,
            "idempotency_key": f"cascade-idem-{trip_id[:8]}",
            "airline": "Air France",
            "flight_number_outbound": "AF100",
            "flight_number_inbound": "AF101",
            "origin_iata": "LYS",
            "destination_iata": "CDG",
            "departure_outbound_at": "2026-11-10T06:00:00Z",
            "arrival_outbound_at": "2026-11-10T07:10:00Z",
            "departure_inbound_at": "2026-11-15T19:00:00Z",
            "arrival_inbound_at": "2026-11-15T20:10:00Z",
            "price_amount": "180.00",
            "currency": "EUR",
            "cabin_class": "ECONOMY",
        },
    )
    assert book_resp.status_code == 201

    gallery = (await client.get(f"/api/v1/places/trip/{trip_id}/gallery", headers=headers)).json()
    first_place = gallery["places"][0]
    visit_resp = await client.post(
        "/api/v1/itinerary/items",
        headers=headers,
        json={
            "trip_id": trip_id,
            "place_id": first_place["id"],
            "visit_date": "2026-11-11",
            "local_start_time": "10:00",
            "duration_minutes": 90,
            "transit_mode": "WALK",
        },
    )
    assert visit_resp.status_code == 201

    res = cleanup_and_verify_cascade_for_emails([email], db_sync_url=test_sync_url)
    assert res["deleted_users"] == 1
    assert res["deleted_trips"] == 1
    assert res["cascade_verified"] is True


def test_dev_database_contains_no_playwright_accounts_after_suite() -> None:
    """
    Échoue si la base de développement ('travelmate_db') contient des comptes 'playwright.*'
    après l'exécution de la suite de tests.
    """
    _, _, dev_sync_url = setup_travelmate_test_database()
    assert DEV_DB_NAME in dev_sync_url

    eng = create_engine(dev_sync_url)
    try:
        with eng.connect() as conn:
            rows = conn.execute(
                text("SELECT email FROM users WHERE lower(email) LIKE 'playwright.%'")
            ).fetchall()
            playwright_accounts = [str(r[0]) for r in rows]
    finally:
        eng.dispose()

    assert playwright_accounts == [], (
        f"La base de développement '{DEV_DB_NAME}' contient des comptes 'playwright.*' : "
        f"{playwright_accounts}"
    )
