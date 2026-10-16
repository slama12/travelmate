from decimal import Decimal
import json
from typing import Any

from httpx import AsyncClient
import pytest

from app.core.providers import get_provider_registry
from app.core.security import get_envelope_cipher


async def _auth_headers(client: AsyncClient) -> dict[str, str]:
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "demo@travelmate.app", "password": "TravelMate2026!"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _create_trip_for_city(
    client: AsyncClient, headers: dict[str, str], city_name: str = "Paris"
) -> dict[str, Any]:
    dests_resp = await client.get("/api/v1/destinations", params={"q": city_name})
    assert dests_resp.status_code == 200
    dest = dests_resp.json()[0]
    trip_resp = await client.post(
        "/api/v1/trips",
        headers=headers,
        json={
            "destination_id": dest["id"],
            "title": f"Séjour Test Étape 2 - {city_name}",
            "travel_style": "STANDARD",
            "total_budget_planned": 2200.0,
            "currency": "EUR",
        },
    )
    assert trip_resp.status_code == 201
    return trip_resp.json()


@pytest.mark.asyncio
async def test_flight_search_and_date_coherence(client: AsyncClient) -> None:
    """Règle 3 : Recherche de vols (dates, IATA, éco/standard/luxe) et validation de cohérence des dates."""
    headers = await _auth_headers(client)
    trip = await _create_trip_for_city(client, headers, "Tokyo")

    # 1. Recherche valide en mode ECONOMIC vs LUXURY
    eco_resp = await client.get(
        "/api/v1/flights/search",
        params={
            "origin_iata": "CDG",
            "destination_iata": "HND",
            "departure_date": "2026-11-10",
            "return_date": "2026-11-20",
            "travel_style": "ECONOMIC",
        },
    )
    assert eco_resp.status_code == 200
    eco_offers = eco_resp.json()
    assert len(eco_offers) >= 2
    assert Decimal(eco_offers[0]["price_amount"]) > Decimal("0.00")
    assert eco_offers[0]["currency"] == "EUR"

    lux_resp = await client.get(
        "/api/v1/flights/search",
        params={
            "origin_iata": "CDG",
            "destination_iata": "HND",
            "departure_date": "2026-11-10",
            "return_date": "2026-11-20",
            "travel_style": "LUXURY",
        },
    )
    assert lux_resp.status_code == 200
    lux_offers = lux_resp.json()
    assert Decimal(lux_offers[0]["price_amount"]) > Decimal(eco_offers[0]["price_amount"])
    assert lux_offers[0]["cabin_class"] == "BUSINESS"

    # 2. Recherche incohérente : retour avant ou égal à l'aller -> 422
    bad_search = await client.get(
        "/api/v1/flights/search",
        params={
            "origin_iata": "CDG",
            "destination_iata": "HND",
            "departure_date": "2026-11-20",
            "return_date": "2026-11-15",
            "travel_style": "STANDARD",
        },
    )
    assert bad_search.status_code == 422

    # 3. Réservation incohérente : départ retour avant l'arrivée aller -> 422
    bad_booking = await client.post(
        "/api/v1/flights/book",
        headers=headers,
        json={
            "trip_id": trip["id"],
            "idempotency_key": "idem-bad-dates-001",
            "airline": "Air France",
            "flight_number_outbound": "AF104",
            "flight_number_inbound": "AF105",
            "origin_iata": "CDG",
            "destination_iata": "HND",
            "departure_outbound_at": "2026-11-10T10:00:00Z",
            "arrival_outbound_at": "2026-11-10T23:00:00Z",
            "departure_inbound_at": "2026-11-10T18:00:00Z",
            "arrival_inbound_at": "2026-11-11T06:00:00Z",
            "price_amount": "780.00",
            "currency": "EUR",
            "cabin_class": "ECONOMY",
        },
    )
    assert bad_booking.status_code == 422


@pytest.mark.asyncio
async def test_flight_booking_updates_trip_vault_budget_and_gmail_with_idempotency(
    client: AsyncClient,
) -> None:
    """
    Règle 3 : Réservation cohérente et idempotente.
    Vérifie : mise à jour de Trip.arrival_at/departure_at, billet chiffré dans VaultDocument,
    dépense Decimal dans BudgetItem, email Gmail envoyé, et absence de doublon au second clic.
    """
    headers = await _auth_headers(client)
    trip = await _create_trip_for_city(client, headers, "Tokyo")

    booking_payload = {
        "trip_id": trip["id"],
        "idempotency_key": "idem-tokyo-flight-2026-001",
        "airline": "Air France",
        "flight_number_outbound": "AF274",
        "flight_number_inbound": "AF275",
        "origin_iata": "CDG",
        "destination_iata": "HND",
        "departure_outbound_at": "2026-11-10T08:30:00Z",
        "arrival_outbound_at": "2026-11-10T21:30:00Z",
        "departure_inbound_at": "2026-11-20T14:15:00Z",
        "arrival_inbound_at": "2026-11-21T03:15:00Z",
        "price_amount": "780.50",
        "currency": "EUR",
        "cabin_class": "ECONOMY",
    }

    # Premier clic : création complète
    first_resp = await client.post("/api/v1/flights/book", headers=headers, json=booking_payload)
    assert first_resp.status_code == 201
    first_data = first_resp.json()
    assert first_data["idempotent_replay"] is False
    assert Decimal(first_data["price_amount"]) == Decimal("780.50")
    assert first_data["currency"] == "EUR"
    assert first_data["gmail_confirmation_sent"] is True
    assert first_data["vault_document_id"] is not None
    assert first_data["budget_item_id"] is not None
    assert "Confirmation billet d'avion CDG -> HND" in first_data["confirmation_email_preview"]["subject"]
    assert all(first_data["transaction_steps"].values())

    # Second clic (même clé d'idempotence) : aucun doublon créé ni second email envoyé
    second_resp = await client.post("/api/v1/flights/book", headers=headers, json=booking_payload)
    assert second_resp.status_code == 201
    second_data = second_resp.json()
    assert second_data["idempotent_replay"] is True
    assert second_data["id"] == first_data["id"]
    assert second_data["pnr_reference"] == first_data["pnr_reference"]
    assert second_data["gmail_message_id"] == first_data["gmail_message_id"]
    assert second_data["vault_document_id"] == first_data["vault_document_id"]
    assert second_data["budget_item_id"] == first_data["budget_item_id"]

    # Vérifie qu'une seule réservation existe sur le voyage
    list_resp = await client.get(f"/api/v1/flights/trip/{trip['id']}", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    # Vérifie que Trip.arrival_at et Trip.departure_at ont bien été mis à jour
    trips_resp = await client.get("/api/v1/trips", headers=headers)
    updated_trip = next(t for t in trips_resp.json() if t["id"] == trip["id"])
    assert updated_trip["status"] == "BOOKED"
    assert updated_trip["arrival_at"].startswith("2026-11-10T21:30:00")
    assert updated_trip["departure_at"].startswith("2026-11-20T14:15:00")


@pytest.mark.asyncio
async def test_flight_booking_post_commit_email_resilience_and_vault_atomic_rollback(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Règle 3 & Correction Étape 3.6 :
    1) Si le coffre-fort échoue avant le commit, la transaction DB est annulée (rollback).
    2) L'email Gmail est envoyé APRÈS le commit : une panne Gmail n'annule PAS la réservation,
       effectue une nouvelle tentative automatique (statut PENDING_RETRY) et permet une relance.
    """
    headers = await _auth_headers(client)
    trip = await _create_trip_for_city(client, headers, "Rome")

    # Partie A : Panne du coffre-fort avant commit -> Rollback atomique complet
    import sys

    flights_router_module = sys.modules["app.modules.flights.router"]

    class _FailingCipher:
        def encrypt_document(self, _plaintext: bytes) -> dict[str, Any]:
            raise RuntimeError("Panne matérielle HSM simulée")

    monkeypatch.setattr(flights_router_module, "get_envelope_cipher", lambda: _FailingCipher())

    vault_fail_resp = await client.post(
        "/api/v1/flights/book",
        headers=headers,
        json={
            "trip_id": trip["id"],
            "idempotency_key": "idem-vault-rollback-rome-001",
            "airline": "ITA Airways",
            "flight_number_outbound": "AZ319",
            "flight_number_inbound": "AZ320",
            "origin_iata": "CDG",
            "destination_iata": "FCO",
            "departure_outbound_at": "2026-09-10T09:00:00Z",
            "arrival_outbound_at": "2026-09-10T11:05:00Z",
            "departure_inbound_at": "2026-09-15T17:00:00Z",
            "arrival_inbound_at": "2026-09-15T19:10:00Z",
            "price_amount": "145.00",
            "currency": "EUR",
            "cabin_class": "ECONOMY",
        },
    )
    assert vault_fail_resp.status_code == 502
    vault_detail = vault_fail_resp.json()["detail"]
    assert vault_detail["failed_step"] == "vault_encrypted"
    assert vault_detail["rolled_back"] is True
    monkeypatch.undo()

    # Partie B : Panne Gmail APRÈS commit -> La réservation reste engagée (201), avec retry
    registry = get_provider_registry()
    orig_send = registry.gmail.send_booking_confirmation

    async def _failing_gmail(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("Erreur SMTP Gmail simulée post-commit")

    monkeypatch.setattr(registry.gmail, "send_booking_confirmation", _failing_gmail)

    post_commit_resp = await client.post(
        "/api/v1/flights/book",
        headers=headers,
        json={
            "trip_id": trip["id"],
            "idempotency_key": "idem-post-commit-rome-002",
            "airline": "ITA Airways",
            "flight_number_outbound": "AZ319",
            "flight_number_inbound": "AZ320",
            "origin_iata": "CDG",
            "destination_iata": "FCO",
            "departure_outbound_at": "2026-09-10T09:00:00Z",
            "arrival_outbound_at": "2026-09-10T11:05:00Z",
            "departure_inbound_at": "2026-09-15T17:00:00Z",
            "arrival_inbound_at": "2026-09-15T19:10:00Z",
            "price_amount": "145.00",
            "currency": "EUR",
            "cabin_class": "ECONOMY",
        },
    )
    assert post_commit_resp.status_code == 201
    booked = post_commit_resp.json()
    assert booked["transaction_steps"]["booking_created"] is True
    assert booked["transaction_steps"]["gmail_sent"] is False
    assert booked["gmail_confirmation_sent"] is False
    assert booked["gmail_send_status"] == "PENDING_RETRY"
    assert booked["gmail_send_attempts"] == 2
    assert "Erreur SMTP Gmail simulée" in (booked["gmail_last_error"] or "")

    # Restauration de Gmail et relance via /retry-email
    monkeypatch.setattr(registry.gmail, "send_booking_confirmation", orig_send)
    retry_resp = await client.post(
        f"/api/v1/flights/{booked['id']}/retry-email",
        headers=headers,
    )
    assert retry_resp.status_code == 200
    retried = retry_resp.json()
    assert retried["gmail_confirmation_sent"] is True
    assert retried["gmail_send_status"] == "SENT"
    assert retried["gmail_send_attempts"] == 3
    assert retried["gmail_last_error"] is None


@pytest.mark.asyncio
async def test_accommodations_search_by_zone_price_source_and_nearby_restaurants(
    client: AsyncClient,
) -> None:
    """
    Règles 4 & 5 : Recherche d'hébergements par zone géographique (lat, lng, rayon) et gamme de prix,
    indication explicite de la source (HOTEL, AIRBNB, SIMULATED) et restaurants proches avec distance calculée.
    """
    # 1. Recherche autour du centre de Paris (rayon 8 km, prix entre 100€ et 1500€)
    resp = await client.get(
        "/api/v1/accommodations/search",
        params={
            "lat": 48.8566,
            "lng": 2.3522,
            "radius_km": 8.0,
            "min_price": "100.00",
            "max_price": "1500.00",
        },
    )
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 2

    types_found = {item["type"] for item in items}
    sources_found = {item["source"] for item in items}
    assert "HOTEL" in types_found
    assert "AIRBNB" in types_found
    assert sources_found.issubset({"HOTEL", "AIRBNB", "SIMULATED"})

    for item in items:
        assert item["distance_from_center_km"] <= 8.0
        assert Decimal("100.00") <= Decimal(item["price_per_night"]) <= Decimal("1500.00")
        assert item["booking_redirect_url"].startswith("https://")
        assert len(item["nearby_restaurants"]) >= 1
        # Vérifie que les distances des restaurants sont triées par ordre croissant et cohérentes
        distances_m = [r["distance_m"] for r in item["nearby_restaurants"]]
        assert distances_m == sorted(distances_m)
        assert item["nearby_restaurants"][0]["distance_km"] > 0
        assert item["nearby_restaurants"][0]["walking_minutes"] >= 1

    # 2. Recherche dans une zone géographique sans hébergement (Océan Atlantique)
    empty_resp = await client.get(
        "/api/v1/accommodations/search",
        params={"lat": 0.0, "lng": 0.0, "radius_km": 5.0},
    )
    assert empty_resp.status_code == 200
    assert empty_resp.json() == []

    # 3. Un filtre accommodation_type invalide (ex. libellé UI "Hôtels + Airbnb") est refusé en 422 explicite
    invalid_type_resp = await client.get(
        "/api/v1/accommodations/search",
        params={
            "lat": 48.8566,
            "lng": 2.3522,
            "radius_km": 12.0,
            "accommodation_type": "Hôtels + Airbnb",
        },
    )
    assert invalid_type_resp.status_code == 422
    assert "accommodation_type invalide" in invalid_type_resp.json()["detail"]


@pytest.mark.asyncio
async def test_places_gallery_unlocked_after_flight_selection_and_wishlist(
    client: AsyncClient,
) -> None:
    """
    Règle 6 : Galerie en grandes photos verrouillée tant que le vol n'est pas réservé,
    puis débloquée après la réservation avec sélection des lieux et favoris (Wishlist).
    """
    headers = await _auth_headers(client)
    trip = await _create_trip_for_city(client, headers, "Paris")

    # 1. Avant réservation du vol : galerie verrouillée
    locked_gallery = await client.get(f"/api/v1/places/trip/{trip['id']}/gallery", headers=headers)
    assert locked_gallery.status_code == 200
    assert locked_gallery.json()["unlocked"] is False
    assert locked_gallery.json()["places"] == []

    # 2. Réservation du vol pour débloquer la galerie
    book_resp = await client.post(
        "/api/v1/flights/book",
        headers=headers,
        json={
            "trip_id": trip["id"],
            "idempotency_key": "idem-unlock-gallery-paris-001",
            "airline": "Air France",
            "flight_number_outbound": "AF101",
            "flight_number_inbound": "AF102",
            "origin_iata": "NCE",
            "destination_iata": "CDG",
            "departure_outbound_at": "2026-10-01T08:00:00Z",
            "arrival_outbound_at": "2026-10-01T09:35:00Z",
            "departure_inbound_at": "2026-10-05T19:00:00Z",
            "arrival_inbound_at": "2026-10-05T20:35:00Z",
            "price_amount": "155.00",
            "currency": "EUR",
            "cabin_class": "ECONOMY",
        },
    )
    assert book_resp.status_code == 201

    # 3. Après réservation : galerie débloquée avec grandes photos
    unlocked_gallery = await client.get(f"/api/v1/places/trip/{trip['id']}/gallery", headers=headers)
    assert unlocked_gallery.status_code == 200
    gallery_data = unlocked_gallery.json()
    assert gallery_data["unlocked"] is True
    assert len(gallery_data["places"]) >= 3
    first_place = gallery_data["places"][0]
    assert len(first_place["hero_photos"]) >= 1

    # 4. Sélection du lieu pour le séjour
    sel_resp = await client.post(
        f"/api/v1/places/trip/{trip['id']}/select",
        headers=headers,
        json={"place_id": first_place["id"], "selected": True},
    )
    assert sel_resp.status_code == 200
    assert first_place["id"] in sel_resp.json()["selected_place_ids"]

    # 5. Ajout aux favoris (Wishlist)
    wish_resp = await client.post(
        f"/api/v1/places/{first_place['id']}/wishlist",
        headers=headers,
        json={"notes": "À visiter absolument au coucher du soleil"},
    )
    assert wish_resp.status_code == 200
    assert wish_resp.json()["wishlisted"] is True


@pytest.mark.asyncio
async def test_world_city_not_in_seed_simulated_error_and_real_provider_caching(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Règle 2 : Villes du monde.
    - En mode simulé : une ville absente du seed (ex: Barcelone) renvoie un message clair
      'ville non disponible en simulation' (404, aucune donnée inventée).
    - En mode réel : le provider réel est interrogé à la demande et mis en cache dans Place et Redis.
    """
    headers = await _auth_headers(client)

    # 1. Résolution dynamique d'une nouvelle ville du monde (Barcelone)
    resolve_resp = await client.post(
        "/api/v1/destinations/resolve",
        json={"city_name": "Barcelone", "country_name": "Espagne", "country_code_iso2": "ES", "iata_code": "BCN"},
    )
    assert resolve_resp.status_code == 200
    assert resolve_resp.json()["city_name"] == "Barcelone"

    # 2. En mode simulé par défaut : renvoie 'Ville Barcelone non disponible en simulation'
    sim_resp = await client.get("/api/v1/places/city/Barcelone", headers=headers)
    assert sim_resp.status_code == 404
    detail = sim_resp.json()["detail"]
    assert detail["code"] == "CITY_NOT_AVAILABLE_IN_SIMULATION"
    assert "non disponible en simulation" in detail["message"].lower()

    # 3. En mode réel : interrogation à la demande et mise en cache dans Place + Redis
    registry = get_provider_registry()

    class _MockRealPlacesProvider:
        mode = "real"

        async def search_city_highlights(
            self, city_name: str, category: str | None = None, travel_style: str = "STANDARD"
        ) -> list[dict[str, Any]]:
            return [
                {
                    "external_place_id": "gplaces-bcn-sagrada",
                    "name": "Basilique de la Sagrada Família",
                    "description": "Chef-d'œuvre moderniste d'Antoni Gaudí à Barcelone.",
                    "category": "CULTURE",
                    "is_outdoor": False,
                    "latitude": 41.4036,
                    "longitude": 2.1744,
                    "recommended_duration_min": 150,
                    "estimated_cost": 26.0,
                    "price_tier": "STANDARD",
                    "avg_rating": 4.9,
                    "opening_hours": {"daily": "09:00-18:00"},
                    "hero_photos": [
                        "https://images.unsplash.com/photo-1583422409516-2895a77efded?auto=format&fit=crop&w=1200&q=80"
                    ],
                    "source_provider": "google_places",
                }
            ]

    monkeypatch.setattr(registry, "places", _MockRealPlacesProvider())

    real_resp = await client.get("/api/v1/places/city/Barcelone", headers=headers)
    assert real_resp.status_code == 200
    real_data = real_resp.json()
    assert real_data["provider_mode"] == "real"
    assert real_data["cached_in_redis"] is True
    assert len(real_data["places"]) == 1
    assert real_data["places"][0]["name"] == "Basilique de la Sagrada Família"
    assert real_data["places"][0]["source_provider"] == "google_places"
