from datetime import date, datetime, timezone

from httpx import AsyncClient
import pytest

from app.core.config import Settings
from app.core.providers import (
    BaseAIProvider,
    BaseCalendarProvider,
    BaseFlightsProvider,
    BaseGmailProvider,
    BasePlacesProvider,
    BaseWeatherProvider,
    ProviderRegistry,
    RealAIProvider,
    RealCalendarProvider,
    RealFlightsProvider,
    RealGmailProvider,
    RealPlacesProvider,
    RealWeatherProvider,
    SimulatedAIProvider,
    SimulatedCalendarProvider,
    SimulatedFlightsProvider,
    SimulatedGmailProvider,
    SimulatedPlacesProvider,
    SimulatedWeatherProvider,
)
from app.core.security import EnvelopeCipher


@pytest.mark.asyncio
async def test_health_endpoint_exposes_all_provider_modes(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "ok"
    assert data["database"]["connected"] is True
    assert "redis" in data

    expected_services = {"gmail", "calendar", "flights", "weather", "ai", "places"}
    assert set(data["providers"].keys()) == expected_services
    assert set(data["active_provider_modes"].keys()) == expected_services

    for svc in expected_services:
        assert data["providers"][svc]["mode"] in ("simulated", "real")
        assert "implementation" in data["providers"][svc]
        assert "env_var" in data["providers"][svc]


@pytest.mark.asyncio
async def test_hybrid_adapters_selection_and_common_interfaces(caplog: pytest.LogCaptureFixture) -> None:
    sim_settings = Settings(
        GMAIL_PROVIDER_MODE="simulated",
        CALENDAR_PROVIDER_MODE="simulated",
        FLIGHTS_PROVIDER_MODE="simulated",
        WEATHER_PROVIDER_MODE="simulated",
        AI_PROVIDER_MODE="simulated",
        PLACES_PROVIDER_MODE="simulated",
    )
    sim_registry = ProviderRegistry(sim_settings)

    assert isinstance(sim_registry.gmail, (BaseGmailProvider, SimulatedGmailProvider))
    assert isinstance(sim_registry.calendar, (BaseCalendarProvider, SimulatedCalendarProvider))
    assert isinstance(sim_registry.flights, (BaseFlightsProvider, SimulatedFlightsProvider))
    assert isinstance(sim_registry.weather, (BaseWeatherProvider, SimulatedWeatherProvider))
    assert isinstance(sim_registry.ai, (BaseAIProvider, SimulatedAIProvider))
    assert isinstance(sim_registry.places, (BasePlacesProvider, SimulatedPlacesProvider))

    with caplog.at_level("INFO"):
        logged_lines = sim_registry.log_active_modes()
    assert len(logged_lines) == 6
    assert any("service=flights" in line and "mode=SIMULATED" in line for line in logged_lines)

    real_settings = Settings(
        GMAIL_PROVIDER_MODE="real",
        CALENDAR_PROVIDER_MODE="real",
        FLIGHTS_PROVIDER_MODE="real",
        WEATHER_PROVIDER_MODE="real",
        AI_PROVIDER_MODE="real",
        PLACES_PROVIDER_MODE="real",
    )
    real_registry = ProviderRegistry(real_settings)

    assert isinstance(real_registry.gmail, (BaseGmailProvider, RealGmailProvider))
    assert isinstance(real_registry.calendar, (BaseCalendarProvider, RealCalendarProvider))
    assert isinstance(real_registry.flights, (BaseFlightsProvider, RealFlightsProvider))
    assert isinstance(real_registry.weather, (BaseWeatherProvider, RealWeatherProvider))
    assert isinstance(real_registry.ai, (BaseAIProvider, RealAIProvider))
    assert isinstance(real_registry.places, (BasePlacesProvider, RealPlacesProvider))


@pytest.mark.asyncio
async def test_simulated_providers_return_realistic_data() -> None:
    registry = ProviderRegistry(Settings())

    flights_eco = await registry.flights.search_flights(
        origin_iata="CDG",
        destination_iata="HND",
        departure_date=date(2026, 11, 10),
        return_date=date(2026, 11, 20),
        travel_style="ECONOMIC",
    )
    flights_lux = await registry.flights.search_flights(
        origin_iata="CDG",
        destination_iata="HND",
        departure_date=date(2026, 11, 10),
        return_date=date(2026, 11, 20),
        travel_style="LUXURY",
    )
    assert len(flights_eco) >= 2
    assert flights_eco[0]["destination_city"] == "Tokyo"
    assert flights_lux[0]["price_eur"] > flights_eco[0]["price_eur"]
    assert flights_lux[0]["cabin_class"] == "BUSINESS"

    places_paris = await registry.places.search_city_highlights("Paris")
    assert any(p["name"] == "Musée du Louvre" for p in places_paris)

    forecast = await registry.weather.get_daily_forecast("Paris", 48.8566, 2.3522, date(2026, 11, 10), days=5)
    assert len(forecast) == 5
    assert any(day["is_rainy"] is True for day in forecast)


def test_vault_envelope_encryption_roundtrip() -> None:
    cipher = EnvelopeCipher()
    secret_passport = b"PASSPORT-NUMBER-FR-99887766"
    bundle = cipher.encrypt_document(secret_passport)

    assert bundle["encrypted_payload"] != secret_passport
    decrypted = cipher.decrypt_document(
        encrypted_payload=bundle["encrypted_payload"],  # type: ignore[arg-type]
        encryption_iv=bundle["encryption_iv"],  # type: ignore[arg-type]
        encrypted_dek=bundle["encrypted_dek"],  # type: ignore[arg-type]
    )
    assert decrypted == secret_passport


@pytest.mark.asyncio
async def test_auth_destinations_and_trips_flow(client: AsyncClient) -> None:
    # 1. Liste des destinations réalistes pré-remplies
    dest_resp = await client.get("/api/v1/destinations")
    assert dest_resp.status_code == 200
    destinations = dest_resp.json()
    assert len(destinations) >= 5
    cities = {d["city_name"] for d in destinations}
    assert {"Paris", "Tokyo", "Rome", "New York", "Marrakech"}.issubset(cities)

    tokyo = next(d for d in destinations if d["city_name"] == "Tokyo")
    assert "monnaie" in tokyo["practical_info"]

    # 2. Inscription d'un nouvel utilisateur
    reg_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "camille@travelmate.app",
            "password": "StrongPassword123!",
            "full_name": "Camille Martin",
            "preferred_style": "ECONOMIC",
        },
    )
    assert reg_resp.status_code == 201
    token = reg_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Bascule en Mode LUXURY
    style_resp = await client.patch(
        "/api/v1/auth/travel-style",
        json={"preferred_style": "LUXURY"},
        headers=headers,
    )
    assert style_resp.status_code == 200
    assert style_resp.json()["preferred_style"] == "LUXURY"

    # 4. Création d'un séjour (Trip) à Tokyo
    trip_resp = await client.post(
        "/api/v1/trips",
        json={
            "destination_id": tokyo["id"],
            "title": "Séjour Automne à Tokyo",
            "travel_style": "LUXURY",
            "total_budget_planned": 4800.0,
            "currency": "EUR",
            "preferences": {"culture": True, "food": True, "nature": True},
            "arrival_at": datetime(2026, 11, 10, 9, 30, tzinfo=timezone.utc).isoformat(),
            "departure_at": datetime(2026, 11, 18, 17, 0, tzinfo=timezone.utc).isoformat(),
        },
        headers=headers,
    )
    assert trip_resp.status_code == 201
    created_trip = trip_resp.json()
    assert created_trip["title"] == "Séjour Automne à Tokyo"
    assert created_trip["travel_style"] == "LUXURY"

    # 5. Lecture des séjours de l'utilisateur
    list_trips_resp = await client.get("/api/v1/trips", headers=headers)
    assert list_trips_resp.status_code == 200
    assert len(list_trips_resp.json()) == 1
