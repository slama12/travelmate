import sys
from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.redis import get_redis_client
import app.modules.destinations.router  # noqa: F401

destinations_router = sys.modules["app.modules.destinations.router"]


LISBONNE_GEONAMES_MOCK_PAYLOAD: dict[str, Any] = {
    "totalResultsCount": 5,
    "geonames": [
        {
            "geonameId": 2267057,
            "name": "Lisbonne",
            "toponymName": "Lisboa",
            "countryName": "Portugal",
            "countryCode": "PT",
            "fcl": "P",
            "fcode": "PPLC",
            "lat": "38.71667",
            "lng": "-9.13333",
            "population": 517802,
            "timezone": {"timeZoneId": "Europe/Lisbon", "gmtOffset": 0.0, "dstOffset": 1.0},
        },
        {
            # Région renvoyée par GeoNames pour q=lisbonne (fcl L) -> doit être filtrée
            "geonameId": 12214098,
            "name": "Lisbon metropolitan area",
            "toponymName": "Área Metropolitana de Lisboa",
            "countryName": "Portugal",
            "countryCode": "PT",
            "fcl": "L",
            "fcode": "RGN",
            "lat": "38.73694",
            "lng": "-9.14268",
            "population": 2870208,
            "timezone": {"timeZoneId": "Europe/Lisbon"},
        },
        {
            # Banlieue avec fcode PPLX -> doit être filtrée
            "geonameId": 2267058,
            "name": "Benfica (banlieue de Lisbonne)",
            "toponymName": "Benfica",
            "countryName": "Portugal",
            "countryCode": "PT",
            "fcl": "P",
            "fcode": "PPLX",
            "lat": "38.7500",
            "lng": "-9.2000",
            "population": 36985,
            "timezone": {"timeZoneId": "Europe/Lisbon"},
        },
        {
            # Banlieue proche (< 25 km de la capitale dans le même pays) -> doit être filtrée
            "geonameId": 2271972,
            "name": "Amadora",
            "toponymName": "Amadora",
            "countryName": "Portugal",
            "countryCode": "PT",
            "fcl": "P",
            "fcode": "PPLA2",
            "lat": "38.75382",
            "lng": "-9.23083",
            "population": 175136,
            "timezone": {"timeZoneId": "Europe/Lisbon"},
        },
        {
            # Doublon même geonameId -> doit être dédoublonné
            "geonameId": 2267057,
            "name": "Lisbonne",
            "toponymName": "Lisboa",
            "countryName": "Portugal",
            "countryCode": "PT",
            "fcl": "P",
            "fcode": "PPLC",
            "lat": "38.71667",
            "lng": "-9.13333",
            "population": 517802,
            "timezone": {"timeZoneId": "Europe/Lisbon"},
        },
    ],
}

SEOUL_GEONAMES_MOCK_PAYLOAD: dict[str, Any] = {
    "totalResultsCount": 1,
    "geonames": [
        {
            "geonameId": 1835848,
            "name": "Séoul",
            "toponymName": "Seoul",
            "countryName": "Corée du Sud",
            "countryCode": "KR",
            "fcl": "P",
            "fcode": "PPLC",
            "lat": "37.566",
            "lng": "126.9784",
            "population": 10349312,
            "timezone": {"timeZoneId": "Asia/Seoul", "gmtOffset": 9.0, "dstOffset": 9.0},
        }
    ],
}

CAIRO_GEONAMES_MOCK_PAYLOAD: dict[str, Any] = {
    "totalResultsCount": 1,
    "geonames": [
        {
            "geonameId": 360630,
            "name": "Le Caire",
            "toponymName": "Cairo",
            "countryName": "Égypte",
            "countryCode": "EG",
            "fcl": "P",
            "fcode": "PPLC",
            "lat": "30.06263",
            "lng": "31.24967",
            "population": 9539673,
            "timezone": {"timeZoneId": "Africa/Cairo", "gmtOffset": 2.0, "dstOffset": 3.0},
        }
    ],
}


@pytest.mark.asyncio
async def test_geonames_search_lisbonne_filters_region_suburb_duplicates_and_extracts_timezone(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    Règle 1 & 7 :
    - searchJSON appelé avec featureClass=P, orderby=population, maxRows=8, lang=fr, style=FULL.
    - Pour Lisbonne, retire la région ('Lisbon metropolitan area', fcl L), la banlieue (fcode PPLX et banlieue satellite < 25 km) et les doublons.
    - Extrait les champs : geonameId, nom, pays, code_pays, coordonnees, fuseau_horaire (timezone.timeZoneId), population.
    """
    cache = get_redis_client()
    await cache.clear_prefix("geonames:")

    captured_params: dict[str, Any] = {}

    async def fake_fetch(q: str, settings: Any) -> dict[str, Any]:
        captured_params["q"] = q
        captured_params["username"] = settings.GEONAMES_USERNAME
        return LISBONNE_GEONAMES_MOCK_PAYLOAD

    monkeypatch.setattr(destinations_router, "fetch_geonames_search_json", fake_fetch)

    resp = await client.get("/api/v1/destinations/search", params={"q": "lisbonne"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["fallback"] is False
    assert body["normalized_query"] == "lisbonne"
    assert len(body["results"]) == 1

    city = body["results"][0]
    assert city["geonameId"] == 2267057
    assert city["nom"] == "Lisbonne"
    assert city["pays"] == "Portugal"
    assert city["code_pays"] == "PT"
    assert city["fuseau_horaire"] == "Europe/Lisbon"
    assert city["population"] == 517802
    assert pytest.approx(city["coordonnees"]["latitude"], rel=1e-4) == 38.71667
    assert pytest.approx(city["coordonnees"]["longitude"], rel=1e-4) == -9.13333

    # Vérifie que la région et les banlieues ont bien été exclues
    names = [r["nom"] for r in body["results"]]
    assert "Lisbon metropolitan area" not in names
    assert "Amadora" not in names


@pytest.mark.asyncio
async def test_geonames_search_seoul_le_caire_unknown_city_and_normalized_redis_cache(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    Règle 1, 2 & 7 :
    - Recherche simulée pour Séoul, Le Caire et une ville inconnue.
    - Cache Redis par requête normalisée (minuscules, sans accents) :
      'Séoul', 'SEOUL' et 'seoul' partagent la même entrée de cache Redis sans second appel GeoNames.
    """
    cache = get_redis_client()
    await cache.clear_prefix("geonames:")

    call_count = {"seoul": 0, "caire": 0, "unknown": 0}

    async def fake_fetch(q: str, settings: Any) -> dict[str, Any]:
        norm = destinations_router.normalize_geonames_query(q)
        if "seoul" in norm:
            call_count["seoul"] += 1
            return SEOUL_GEONAMES_MOCK_PAYLOAD
        if "caire" in norm:
            call_count["caire"] += 1
            return CAIRO_GEONAMES_MOCK_PAYLOAD
        call_count["unknown"] += 1
        return {"totalResultsCount": 0, "geonames": []}

    monkeypatch.setattr(destinations_router, "fetch_geonames_search_json", fake_fetch)

    # 1. Séoul avec accents et majuscules -> 1er appel GeoNames
    r1 = await client.get("/api/v1/destinations/search", params={"q": "Séoul"})
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["available"] is True
    assert d1["cached"] is False
    assert d1["normalized_query"] == "seoul"
    assert len(d1["results"]) == 1
    assert d1["results"][0]["geonameId"] == 1835848
    assert d1["results"][0]["nom"] == "Séoul"
    assert d1["results"][0]["fuseau_horaire"] == "Asia/Seoul"
    assert call_count["seoul"] == 1

    # 2. 'SEOUL' sans accent -> servi depuis le cache Redis normalisé (aucun nouvel appel GeoNames)
    r2 = await client.get("/api/v1/destinations/search", params={"q": "  SEOUL  "})
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["available"] is True
    assert d2["cached"] is True
    assert d2["results"][0]["geonameId"] == 1835848
    assert call_count["seoul"] == 1

    # 3. Le Caire
    r3 = await client.get("/api/v1/destinations/search", params={"q": "Le Caire"})
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["available"] is True
    assert len(d3["results"]) == 1
    assert d3["results"][0]["geonameId"] == 360630
    assert d3["results"][0]["nom"] == "Le Caire"
    assert d3["results"][0]["code_pays"] == "EG"
    assert d3["results"][0]["fuseau_horaire"] == "Africa/Cairo"

    # 4. Ville inconnue -> liste vide propre sans plantage
    r4 = await client.get("/api/v1/destinations/search", params={"q": "ZorglubvilleInconnue"})
    assert r4.status_code == 200
    d4 = r4.json()
    assert d4["available"] is True
    assert d4["fallback"] is False
    assert d4["results"] == []


@pytest.mark.asyncio
async def test_geonames_fallbacks_network_error_quota_and_missing_key(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    Règle 2, 6 & 7 :
    - GeoNames injoignable (erreur réseau), quota atteint (1000/h, 20000/j, par utilisateur ou code GeoNames 19) ou clé absente :
      message 'Recherche de villes indisponible' (et message explicite sur le quota si atteint) + repli sur les 5 villes du seed, jamais de plantage.
    """
    cache = get_redis_client()
    settings = get_settings()

    # Cas A : Clé / identifiant GeoNames absent
    await cache.clear_prefix("geonames:")
    monkeypatch.setattr(settings, "GEONAMES_USERNAME", "")
    resp_missing = await client.get("/api/v1/destinations/search", params={"q": "lisbonne"})
    assert resp_missing.status_code == 200
    body_missing = resp_missing.json()
    assert body_missing["available"] is False
    assert body_missing["fallback"] is True
    assert body_missing["reason"] == "missing_api_key"
    assert "Recherche de villes indisponible" in body_missing["message"]
    assert len(body_missing["fallback_cities"]) == 5

    # Restaure la clé pour les cas suivants
    monkeypatch.setattr(settings, "GEONAMES_USERNAME", "slama12")

    # Cas B : Erreur réseau (GeoNames injoignable)
    await cache.clear_prefix("geonames:")

    async def fake_network_error(q: str, s: Any) -> dict[str, Any]:
        raise httpx.ConnectError("Connection refused to api.geonames.org")

    monkeypatch.setattr(destinations_router, "fetch_geonames_search_json", fake_network_error)
    resp_net = await client.get("/api/v1/destinations/search", params={"q": "berlin"})
    assert resp_net.status_code == 200
    body_net = resp_net.json()
    assert body_net["available"] is False
    assert body_net["fallback"] is True
    assert body_net["reason"] == "network_error"
    assert "Recherche de villes indisponible" in body_net["message"]
    assert len(body_net["fallback_cities"]) == 5

    # Cas C : Quota atteint (limite horaire / utilisateur)
    await cache.clear_prefix("geonames:")
    monkeypatch.setattr(settings, "GEONAMES_HOURLY_QUOTA", 1)

    async def fake_ok(q: str, s: Any) -> dict[str, Any]:
        return LISBONNE_GEONAMES_MOCK_PAYLOAD

    monkeypatch.setattr(destinations_router, "fetch_geonames_search_json", fake_ok)

    first_ok = await client.get("/api/v1/destinations/search", params={"q": "lisbonne"})
    assert first_ok.status_code == 200
    assert first_ok.json()["available"] is True

    second_quota = await client.get("/api/v1/destinations/search", params={"q": "madrid"})
    assert second_quota.status_code == 200
    body_quota = second_quota.json()
    assert body_quota["available"] is False
    assert body_quota["fallback"] is True
    assert body_quota["quota_exceeded"] is True
    assert "Recherche de villes indisponible" in body_quota["message"]
    assert "quota" in body_quota["message"].lower()
    assert len(body_quota["fallback_cities"]) == 5


@pytest.mark.asyncio
async def test_create_world_city_without_duplicate_and_non_seed_gallery_flights_accommodations(
    client: AsyncClient,
):
    """
    Règle 3, 4, 5 & 7 :
    - Création d'une destination hors seed à partir d'un résultat GeoNames (identifiée par geonameId, sans doublon).
    - Les 5 villes du seed gardent leurs données de démonstration et restent proposées en destinations populaires.
    - Pour une ville hors seed :
      * La galerie de lieux affiche 'Les lieux de cette ville arrivent bientôt' (aucune donnée inventée).
      * Vols et hébergements restent simulés : message clair indiquant que la ville n'est pas couverte.
    """
    reg_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "world.cities.step1@travelmate.app",
            "full_name": "Camille Monde",
            "password": "StrongPassword!2026",
            "preferred_style": "STANDARD",
        },
    )
    assert reg_resp.status_code == 201
    token = reg_resp.json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {token}"}

    lisbonne_payload = {
        "geonameId": 2267057,
        "nom": "Lisbonne",
        "pays": "Portugal",
        "code_pays": "PT",
        "coordonnees": {"latitude": 38.71667, "longitude": -9.13333},
        "fuseau_horaire": "Europe/Lisbon",
        "population": 517802,
    }

    # 1. Création via POST /api/v1/destinations/resolve
    c1 = await client.post("/api/v1/destinations/resolve", json=lisbonne_payload)
    assert c1.status_code == 200
    dest1 = c1.json()
    assert dest1["geonameId"] == 2267057
    assert dest1["city_name"] == "Lisbonne"
    assert dest1["country_name"] == "Portugal"
    assert dest1["country_code_iso2"] == "PT"
    assert dest1["timezone"] == "Europe/Lisbon"
    assert dest1["population"] == 517802
    assert dest1["is_seed"] is False

    # 2. Second appel avec le même geonameId (via POST /api/v1/destinations) -> aucun doublon créé
    c2 = await client.post("/api/v1/destinations", json=lisbonne_payload)
    assert c2.status_code in (200, 201)
    dest2 = c2.json()
    assert dest2["id"] == dest1["id"]
    assert dest2["geonameId"] == 2267057

    # 3. Les 5 villes populaires du seed restent intactes et conservent leurs données de démo
    pop_resp = await client.get("/api/v1/destinations", params={"popular_only": "true"})
    assert pop_resp.status_code == 200
    pop_cities = pop_resp.json()
    assert len(pop_cities) == 5
    pop_names = {c["city_name"] for c in pop_cities}
    assert pop_names == {"Paris", "Marrakech", "Tokyo", "New York", "Rome"}

    # 4. Création d'un séjour (Trip) sur la ville hors seed (Lisbonne)
    trip_resp = await client.post(
        "/api/v1/trips",
        headers=auth_headers,
        json={
            "destination_id": dest1["id"],
            "title": "Séjour à Lisbonne",
            "travel_style": "STANDARD",
            "total_budget_planned": "1800.00",
            "currency": "EUR",
            "arrival_at": "2026-11-10T10:30:00Z",
            "departure_at": "2026-11-17T18:00:00Z",
        },
    )
    assert trip_resp.status_code == 201
    trip = trip_resp.json()

    # 5. Galerie de lieux pour Lisbonne -> "Les lieux de cette ville arrivent bientôt", aucune donnée inventée
    gallery_resp = await client.get(
        f"/api/v1/places/trip/{trip['id']}/gallery",
        headers=auth_headers,
    )
    assert gallery_resp.status_code == 200
    gallery = gallery_resp.json()
    assert gallery["unlocked"] is True
    assert gallery["places"] == []
    assert gallery["unlock_message"] == "Les lieux de cette ville arrivent bientôt"

    # 6. Vols simulés pour Lisbonne -> aucun vol inventé + message clair dans l'en-tête
    flights_resp = await client.get(
        "/api/v1/flights/search",
        params={
            "origin_iata": "CDG",
            "trip_id": trip["id"],
            "departure_date": "2026-11-10",
            "return_date": "2026-11-17",
        },
    )
    assert flights_resp.status_code == 200
    assert flights_resp.json() == []
    assert flights_resp.headers.get("X-Simulation-Covered") == "false"
    assert "n'est pas couverte en simulation" in flights_resp.headers.get("X-Simulation-Message", "")

    # 7. Hébergements simulés pour Lisbonne -> aucun hébergement inventé + message clair
    acc_resp = await client.get(
        "/api/v1/accommodations/search",
        params={"trip_id": trip["id"]},
    )
    assert acc_resp.status_code == 200
    assert acc_resp.json() == []
    assert acc_resp.headers.get("X-Simulation-Covered") == "false"
    assert "n'est pas couverte en simulation" in acc_resp.headers.get("X-Simulation-Message", "")
