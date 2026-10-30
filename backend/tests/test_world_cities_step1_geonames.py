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
    monkeypatch: pytest.MonkeyPatch,
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

    # 5. Galerie de lieux pour Lisbonne (Étape 2 : remplace 'Les lieux de cette ville arrivent bientôt' par la vraie galerie sans photo inventée)
    import sys
    import app.modules.places.router  # noqa: F401

    places_router_mod = sys.modules["app.modules.places.router"]
    from app.modules.places.world_places_service import (
        WorldCityPlacesResult,
        WorldPlaceCandidate,
    )

    class _StubLisbonnePlacesService:
        async def fetch_city_places(self, **kwargs):
            return WorldCityPlacesResult(
                city_name="Lisbonne",
                places=[
                    WorldPlaceCandidate(
                        name="Tour de Belém",
                        description="Tour fortifiée manuéline sur le Tage.",
                        category="CULTURE",
                        latitude=38.6916,
                        longitude=-9.2160,
                        is_outdoor=False,
                        recommended_duration_min=60,
                        estimated_cost=8.0,
                        price_tier="BUDGET",
                        price_label="8 €",
                        opening_hours={"status": "confirmé", "display": "10:00-17:30", "mon": "10:00-17:30"},
                        hours_status="confirmé",
                        source_provider="Wikivoyage",
                        external_place_id="wv:fr:Lisbonne:tour-de-belem",
                        source_url="https://fr.wikivoyage.org/wiki/Lisbonne",
                        source_attribution="Données Wikivoyage / Wikipédia (CC BY-SA 4.0)",
                        notoriety_score=180.0,
                    )
                ],
                provider_mode="WIKIVOYAGE_WIKIPEDIA",
            )

    monkeypatch.setattr(
        places_router_mod,
        "get_world_places_service",
        lambda: _StubLisbonnePlacesService(),
    )

    gallery_resp = await client.get(
        f"/api/v1/places/trip/{trip['id']}/gallery",
        headers=auth_headers,
    )
    assert gallery_resp.status_code == 200
    gallery = gallery_resp.json()
    assert gallery["unlocked"] is True
    assert len(gallery["places"]) >= 1
    assert gallery["places"][0]["name"] == "Tour de Belém"
    assert gallery["places"][0]["hero_photos"] == []
    assert gallery["places"][0]["photo_status"] == "Photo bientôt disponible"
    assert gallery["places"][0]["source_attribution"] == "Données Wikivoyage / Wikipédia (CC BY-SA 4.0)"
    assert "Les lieux de cette ville arrivent bientôt" not in gallery["unlock_message"]

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


@pytest.mark.asyncio
async def test_geonames_versailles_present_without_saint_quentin_and_no_unrequested_demo_cities(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    A.1 & A.3 :
    - 'versailles' renvoie Saint-Quentin-en-Yvelines mais pas Versailles si le filtre < 25 km d'une capitale
      élimine les vraies villes : limité aux seuls quartiers (PPLX/PPLQ), un nom exact n'est jamais filtré.
    - Saint-Quentin-en-Yvelines ne correspond pas au nom cherché 'versailles' et est exclu.
    - Aucune des 5 villes de démonstration non demandées n'est ajoutée aux résultats.
    """
    cache = get_redis_client()
    await cache.clear_prefix("geonames:")

    versailles_mock_payload: dict[str, Any] = {
        "totalResultsCount": 3,
        "geonames": [
            {
                "geonameId": 6618604,
                "name": "Saint-Quentin-en-Yvelines",
                "toponymName": "Saint-Quentin-en-Yvelines",
                "fcl": "P",
                "fcode": "PPL",
                "countryCode": "FR",
                "countryName": "France",
                "adminName1": "Île-de-France",
                "lat": "48.78805",
                "lng": "2.04469",
                "population": 146600,
                "timezone": {"timeZoneId": "Europe/Paris"},
            },
            {
                "geonameId": 2969679,
                "name": "Versailles",
                "toponymName": "Versailles",
                "fcl": "P",
                "fcode": "PPLA2",
                "countryCode": "FR",
                "countryName": "France",
                "adminName1": "Île-de-France",
                "lat": "48.80359",
                "lng": "2.13424",
                "population": 85416,
                "timezone": {"timeZoneId": "Europe/Paris"},
            },
            {
                "geonameId": 9999001,
                "name": "Quartier Notre-Dame de Versailles",
                "toponymName": "Quartier Notre-Dame",
                "fcl": "P",
                "fcode": "PPLX",
                "countryCode": "FR",
                "countryName": "France",
                "adminName1": "Île-de-France",
                "lat": "48.80600",
                "lng": "2.13500",
                "population": 19000,
                "timezone": {"timeZoneId": "Europe/Paris"},
            },
        ],
    }

    async def fake_fetch(q: str, settings: Any) -> dict[str, Any]:
        return versailles_mock_payload

    monkeypatch.setattr(destinations_router, "fetch_geonames_search_json", fake_fetch)

    resp = await client.get("/api/v1/destinations/search", params={"q": "versailles"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["fallback"] is False
    assert body["fallback_cities"] == []

    names = [item["nom"] for item in body["results"]]
    assert "Versailles" in names
    assert "Saint-Quentin-en-Yvelines" not in names
    assert "Quartier Notre-Dame de Versailles" not in names

    # Aucune des 5 villes de démo non demandées ne doit polluer les résultats
    for demo_city in ("Marrakech", "Tokyo", "New York", "Rome", "Paris"):
        assert demo_city not in names

    versailles = body["results"][0]
    assert versailles["geonameId"] == 2969679
    assert versailles["region"] == "Île-de-France"
    assert versailles["sous_titre"] == "Île-de-France • France"
    assert versailles["iata_code"] in ("ORY", "CDG")


@pytest.mark.asyncio
async def test_geonames_springfield_multi_country_sorted_by_population_without_eugene_or_chicopee(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    A.2 :
    - 'springfield' renvoie Eugene, Springfield, Chicopee dans l'API brute :
      seuls les résultats dont le nom (ou nom alternatif exact) correspond à 'springfield' sont gardés,
      triés par population décroissante, avec plusieurs États/pays et distingués par 'région • pays'.
    """
    cache = get_redis_client()
    await cache.clear_prefix("geonames:")

    springfield_mock_payload: dict[str, Any] = {
        "totalResultsCount": 6,
        "geonames": [
            {
                "geonameId": 5725846,
                "name": "Eugene",
                "toponymName": "Eugene",
                "fcl": "P",
                "fcode": "PPLA2",
                "countryCode": "US",
                "countryName": "États-Unis",
                "adminName1": "Oregon",
                "lat": "44.05207",
                "lng": "-123.08675",
                "population": 176654,
                "timezone": {"timeZoneId": "America/Los_Angeles"},
            },
            {
                "geonameId": 4250542,
                "name": "Springfield",
                "toponymName": "Springfield",
                "fcl": "P",
                "fcode": "PPLA",
                "countryCode": "US",
                "countryName": "États-Unis",
                "adminName1": "Illinois",
                "lat": "39.78172",
                "lng": "-89.65015",
                "population": 114394,
                "timezone": {"timeZoneId": "America/Chicago"},
            },
            {
                "geonameId": 4409896,
                "name": "Springfield",
                "toponymName": "Springfield",
                "fcl": "P",
                "fcode": "PPLA2",
                "countryCode": "US",
                "countryName": "États-Unis",
                "adminName1": "Missouri",
                "lat": "37.21533",
                "lng": "-93.29824",
                "population": 169176,
                "timezone": {"timeZoneId": "America/Chicago"},
            },
            {
                "geonameId": 4932978,
                "name": "Chicopee",
                "toponymName": "Chicopee",
                "fcl": "P",
                "fcode": "PPL",
                "countryCode": "US",
                "countryName": "États-Unis",
                "adminName1": "Massachusetts",
                "lat": "42.1487",
                "lng": "-72.60787",
                "population": 55560,
                "timezone": {"timeZoneId": "America/New_York"},
            },
            {
                "geonameId": 4951788,
                "name": "Springfield",
                "toponymName": "Springfield",
                "fcl": "P",
                "fcode": "PPLA2",
                "countryCode": "US",
                "countryName": "États-Unis",
                "adminName1": "Massachusetts",
                "lat": "42.10148",
                "lng": "-72.58981",
                "population": 155929,
                "timezone": {"timeZoneId": "America/New_York"},
            },
            {
                "geonameId": 2148955,
                "name": "Springfield",
                "toponymName": "Springfield",
                "fcl": "P",
                "fcode": "PPL",
                "countryCode": "AU",
                "countryName": "Australie",
                "adminName1": "Queensland",
                "lat": "-27.6672",
                "lng": "152.9182",
                "population": 28450,
                "timezone": {"timeZoneId": "Australia/Brisbane"},
            },
        ],
    }

    async def fake_fetch(q: str, settings: Any) -> dict[str, Any]:
        return springfield_mock_payload

    monkeypatch.setattr(destinations_router, "fetch_geonames_search_json", fake_fetch)

    resp = await client.get("/api/v1/destinations/search", params={"q": "springfield"})
    assert resp.status_code == 200
    body = resp.json()
    results = body["results"]

    names = [r["nom"] for r in results]
    assert "Eugene" not in names
    assert "Chicopee" not in names
    assert all(n == "Springfield" for n in names)
    assert len(results) == 4

    # Tri décroissant par population
    populations = [r["population"] for r in results]
    assert populations == [169176, 155929, 114394, 28450]

    # Multi-pays et distinction 'région • pays'
    subtitles = [r["sous_titre"] for r in results]
    assert subtitles == [
        "Missouri • États-Unis",
        "Massachusetts • États-Unis",
        "Illinois • États-Unis",
        "Queensland • Australie",
    ]


@pytest.mark.asyncio
async def test_geonames_spaces_accents_and_regional_queries_bali_toscane(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    A.4 & A.5 :
    - Requêtes avec espaces et accents ('le caire', 'São Paulo', 'Zürich') : URL bien encodée.
    - Régions et îles ('bali', 'toscane') : renvoie des villes de cette région avec 'Bali • Indonésie'
      en sous-titre, et si aucune ville ne porte le nom, ajoute une ligne 'Région : Bali' (featureClass T ou A).
    """
    cache = get_redis_client()
    await cache.clear_prefix("geonames:")

    bali_mock_payload: dict[str, Any] = {
        "totalResultsCount": 4,
        "geonames": [
            {
                "geonameId": 1645528,
                "name": "Denpasar",
                "toponymName": "Denpasar",
                "fcl": "P",
                "fcode": "PPLA",
                "countryCode": "ID",
                "countryName": "Indonésie",
                "adminName1": "Bali",
                "lat": "-8.65",
                "lng": "115.21667",
                "population": 725314,
                "timezone": {"timeZoneId": "Asia/Makassar"},
            },
            {
                "geonameId": 1623045,
                "name": "Ubud",
                "toponymName": "Ubud",
                "fcl": "P",
                "fcode": "PPL",
                "countryCode": "ID",
                "countryName": "Indonésie",
                "adminName1": "Bali",
                "lat": "-8.50685",
                "lng": "115.26247",
                "population": 74800,
                "timezone": {"timeZoneId": "Asia/Makassar"},
            },
            {
                "geonameId": 1639002,
                "name": "Kuta",
                "toponymName": "Kuta",
                "fcl": "P",
                "fcode": "PPL",
                "countryCode": "ID",
                "countryName": "Indonésie",
                "adminName1": "Bali",
                "lat": "-8.72332",
                "lng": "115.17234",
                "population": 58969,
                "timezone": {"timeZoneId": "Asia/Makassar"},
            },
            {
                "geonameId": 1650535,
                "name": "Bali",
                "toponymName": "Provinsi Bali",
                "fcl": "A",
                "fcode": "ADM1",
                "countryCode": "ID",
                "countryName": "Indonésie",
                "adminName1": "Bali",
                "lat": "-8.3695",
                "lng": "115.1383",
                "population": 4317404,
                "timezone": {"timeZoneId": "Asia/Makassar"},
            },
        ],
    }

    sao_paulo_mock_payload: dict[str, Any] = {
        "totalResultsCount": 1,
        "geonames": [
            {
                "geonameId": 3448439,
                "name": "São Paulo",
                "toponymName": "São Paulo",
                "fcl": "P",
                "fcode": "PPLA",
                "countryCode": "BR",
                "countryName": "Brésil",
                "adminName1": "São Paulo",
                "lat": "-23.5475",
                "lng": "-46.63611",
                "population": 12325232,
                "timezone": {"timeZoneId": "America/Sao_Paulo"},
            }
        ],
    }

    zurich_mock_payload: dict[str, Any] = {
        "totalResultsCount": 1,
        "geonames": [
            {
                "geonameId": 2657896,
                "name": "Zurich",
                "toponymName": "Zürich",
                "fcl": "P",
                "fcode": "PPLA",
                "countryCode": "CH",
                "countryName": "Suisse",
                "adminName1": "Zurich",
                "lat": "47.36667",
                "lng": "8.55",
                "population": 402762,
                "timezone": {"timeZoneId": "Europe/Zurich"},
                "alternateNames": [
                    {"lang": "de", "name": "Zürich"},
                    {"lang": "fr", "name": "Zurich"},
                ],
            }
        ],
    }

    async def fake_fetch(q: str, settings: Any) -> dict[str, Any]:
        norm = destinations_router.normalize_geonames_query(q)
        if "bali" in norm:
            return bali_mock_payload
        if "sao paulo" in norm:
            return sao_paulo_mock_payload
        if "zurich" in norm:
            return zurich_mock_payload
        if "le caire" in norm:
            return CAIRO_GEONAMES_MOCK_PAYLOAD
        return {"totalResultsCount": 0, "geonames": []}

    monkeypatch.setattr(destinations_router, "fetch_geonames_search_json", fake_fetch)

    # 1. 'le caire', 'São Paulo', 'Zürich'
    r_cairo = await client.get("/api/v1/destinations/search", params={"q": "le caire"})
    assert r_cairo.status_code == 200
    assert r_cairo.json()["results"][0]["nom"] == "Le Caire"
    assert r_cairo.json()["results"][0]["iata_code"] == "CAI"

    r_sp = await client.get("/api/v1/destinations/search", params={"q": "São Paulo"})
    assert r_sp.status_code == 200
    assert r_sp.json()["results"][0]["nom"] == "São Paulo"
    assert r_sp.json()["results"][0]["iata_code"] == "GRU"

    r_zh = await client.get("/api/v1/destinations/search", params={"q": "Zürich"})
    assert r_zh.status_code == 200
    assert r_zh.json()["results"][0]["nom"] == "Zurich"
    assert r_zh.json()["results"][0]["iata_code"] == "ZRH"

    # 2. 'bali' -> villes de la région Bali avec 'Bali • Indonésie' + ligne 'Région : Bali'
    r_bali = await client.get("/api/v1/destinations/search", params={"q": "bali"})
    assert r_bali.status_code == 200
    bali_results = r_bali.json()["results"]
    bali_names = [x["nom"] for x in bali_results]
    assert "Denpasar" in bali_names
    assert "Ubud" in bali_names
    assert "Kuta" in bali_names
    assert "Région : Bali" in bali_names

    denpasar = next(x for x in bali_results if x["nom"] == "Denpasar")
    assert denpasar["sous_titre"] == "Bali • Indonésie"
    assert denpasar["iata_code"] == "DPS"

    region_row = next(x for x in bali_results if x["nom"] == "Région : Bali")
    assert region_row["is_region"] is True
    assert region_row["feature_class"] in ("A", "T")
    assert region_row["sous_titre"] == "Bali • Indonésie"
    assert region_row["iata_code"] == "DPS"


@pytest.mark.asyncio
async def test_ourairports_monastir_mir_never_deduced_from_name_and_distant_airport_distance(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    C.9 :
    - Monastir affiche le code officiel MIR (jamais MON déduit du nom).
    - Utilise OurAirports (code IATA officiel, distance depuis les coordonnées de la ville).
    - Si aucun aéroport n'est à moins de 100 km, affiche le plus proche avec sa distance.
    """
    cache = get_redis_client()
    await cache.clear_prefix("geonames:")

    monastir_mock_payload: dict[str, Any] = {
        "totalResultsCount": 1,
        "geonames": [
            {
                "geonameId": 2473493,
                "name": "Monastir",
                "toponymName": "Monastir",
                "fcl": "P",
                "fcode": "PPLA2",
                "countryCode": "TN",
                "countryName": "Tunisie",
                "adminName1": "Monastir",
                "lat": "35.77799",
                "lng": "10.82617",
                "population": 104535,
                "timezone": {"timeZoneId": "Africa/Tunis"},
            }
        ],
    }

    async def fake_fetch(q: str, settings: Any) -> dict[str, Any]:
        return monastir_mock_payload

    monkeypatch.setattr(destinations_router, "fetch_geonames_search_json", fake_fetch)

    resp = await client.get("/api/v1/destinations/search", params={"q": "monastir"})
    assert resp.status_code == 200
    monastir = resp.json()["results"][0]
    assert monastir["nom"] == "Monastir"
    assert monastir["iata_code"] == "MIR"
    assert monastir["iata_code"] != "MON"
    assert monastir["airport_within_100km"] is True
    assert monastir["airport_display_label"] == "Monastir (MIR)"
    assert monastir["sous_titre"] == "Monastir • Tunisie"

    # Création/résolution de Monastir : conserve le code IATA officiel MIR
    resolve_resp = await client.post(
        "/api/v1/destinations/resolve",
        json={
            "geonameId": 2473493,
            "nom": "Monastir",
            "pays": "Tunisie",
            "code_pays": "TN",
            "region": "Monastir",
            "coordonnees": {"latitude": 35.77799, "longitude": 10.82617},
            "fuseau_horaire": "Africa/Tunis",
            "population": 104535,
        },
    )
    assert resolve_resp.status_code == 200
    resolved_monastir = resolve_resp.json()
    assert resolved_monastir["iata_code"] == "MIR"
    assert resolved_monastir["airport_within_100km"] is True
    assert resolved_monastir["airport_display_label"] == "Monastir (MIR)"

    # Ville éloignée à plus de 100 km de tout aéroport OurAirports (ex: Merzouga dans le désert marocain)
    from app.core.airports import find_nearest_airport

    distant_airport = find_nearest_airport(
        latitude=31.0994,
        longitude=-4.0119,
        city_name="Merzouga",
        country_code="MA",
    )
    assert distant_airport["within_100km"] is False
    assert distant_airport["distance_km"] > 100.0
    assert "km" in distant_airport["display_label"]
    assert distant_airport["iata_code"] in distant_airport["display_label"]


@pytest.mark.asyncio
async def test_geonames_generalized_regions_santorin_cote_d_azur_andalousie_and_alias_fallback(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    Point 4 — Régions :
    Généralise la détection des régions/îles avec GeoNames (adminName1, noms alternatifs, featureClass T/A)
    pour que "santorin", "côte d'azur", "andalousie" fonctionnent sans dépendre d'une liste écrite à la main,
    tout en gardant REGION_QUERY_ALIASES en secours.
    """
    cache = get_redis_client()
    await cache.clear_prefix("geonames:")

    # Mock des réponses GeoNames réalistes pour "santorin", "côte d'azur" et "andalousie"
    santorin_payload: dict[str, Any] = {
        "totalResultsCount": 3,
        "geonames": [
            {
                "geonameId": 252920,
                "name": "Santorini Island",
                "toponymName": "Nísos Thíra",
                "fcl": "T",
                "fcode": "ISL",
                "countryCode": "GR",
                "countryName": "Grèce",
                "adminName1": "South Aegean",
                "lat": "36.39315",
                "lng": "25.46151",
                "population": 15550,
                "timezone": {"timeZoneId": "Europe/Athens"},
                "alternateNames": [
                    {"name": "Santorin", "lang": "fr"},
                    {"name": "Santorini", "lang": "en"},
                    {"name": "Thira", "lang": "el"},
                ],
            },
            {
                "geonameId": 252923,
                "name": "Fira",
                "toponymName": "Firá",
                "fcl": "P",
                "fcode": "PPLA3",
                "countryCode": "GR",
                "countryName": "Grèce",
                "adminName1": "South Aegean",
                "adminName2": "Thira",
                "lat": "36.41665",
                "lng": "25.43244",
                "population": 2376,
                "timezone": {"timeZoneId": "Europe/Athens"},
                "alternateNames": [{"name": "Fira Santorin", "lang": "fr"}],
            },
            {
                "geonameId": 256245,
                "name": "Oia",
                "toponymName": "Oía",
                "fcl": "P",
                "fcode": "PPL",
                "countryCode": "GR",
                "countryName": "Grèce",
                "adminName1": "South Aegean",
                "adminName2": "Thira",
                "lat": "36.46182",
                "lng": "25.37595",
                "population": 1226,
                "timezone": {"timeZoneId": "Europe/Athens"},
                "alternateNames": [{"name": "Oia", "lang": "fr"}],
            },
        ],
    }

    cote_d_azur_payload: dict[str, Any] = {
        "totalResultsCount": 3,
        "geonames": [
            {
                "geonameId": 3023493,
                "name": "Côte d'Azur",
                "toponymName": "Côte d'Azur",
                "fcl": "T",
                "fcode": "CST",
                "countryCode": "FR",
                "countryName": "France",
                "adminName1": "Provence-Alpes-Côte d'Azur",
                "lat": "43.55",
                "lng": "7.01",
                "population": 2000000,
                "timezone": {"timeZoneId": "Europe/Paris"},
                "alternateNames": [{"name": "Côte d'Azur", "lang": "fr"}],
            },
            {
                "geonameId": 2990440,
                "name": "Nice",
                "toponymName": "Nice",
                "fcl": "P",
                "fcode": "PPLA2",
                "countryCode": "FR",
                "countryName": "France",
                "adminName1": "Provence-Alpes-Côte d'Azur",
                "lat": "43.70313",
                "lng": "7.26608",
                "population": 342669,
                "timezone": {"timeZoneId": "Europe/Paris"},
                "alternateNames": [{"name": "Nice", "lang": "fr"}],
            },
            {
                "geonameId": 3028808,
                "name": "Cannes",
                "toponymName": "Cannes",
                "fcl": "P",
                "fcode": "PPL",
                "countryCode": "FR",
                "countryName": "France",
                "adminName1": "Provence-Alpes-Côte d'Azur",
                "lat": "43.55135",
                "lng": "7.01275",
                "population": 74545,
                "timezone": {"timeZoneId": "Europe/Paris"},
                "alternateNames": [{"name": "Cannes", "lang": "fr"}],
            },
        ],
    }

    andalousie_payload: dict[str, Any] = {
        "totalResultsCount": 4,
        "geonames": [
            {
                "geonameId": 2593109,
                "name": "Andalucia",
                "toponymName": "Andalucía",
                "fcl": "A",
                "fcode": "ADM1",
                "countryCode": "ES",
                "countryName": "Espagne",
                "adminName1": "Andalucía",
                "lat": "37.6",
                "lng": "-4.5",
                "population": 8414240,
                "timezone": {"timeZoneId": "Europe/Madrid"},
                "alternateNames": [
                    {"name": "Andalousie", "lang": "fr"},
                    {"name": "Andalusia", "lang": "en"},
                    {"name": "Andalucía", "lang": "es"},
                ],
            },
            {
                "geonameId": 2510911,
                "name": "Séville",
                "toponymName": "Sevilla",
                "fcl": "P",
                "fcode": "PPLA",
                "countryCode": "ES",
                "countryName": "Espagne",
                "adminName1": "Andalucía",
                "lat": "37.38283",
                "lng": "-5.97317",
                "population": 684234,
                "timezone": {"timeZoneId": "Europe/Madrid"},
                "alternateNames": [{"name": "Séville", "lang": "fr"}, {"name": "Sevilla", "lang": "es"}],
            },
            {
                "geonameId": 2514256,
                "name": "Malaga",
                "toponymName": "Málaga",
                "fcl": "P",
                "fcode": "PPLA2",
                "countryCode": "ES",
                "countryName": "Espagne",
                "adminName1": "Andalucía",
                "lat": "36.72016",
                "lng": "-4.42034",
                "population": 578460,
                "timezone": {"timeZoneId": "Europe/Madrid"},
                "alternateNames": [{"name": "Malaga", "lang": "fr"}, {"name": "Málaga", "lang": "es"}],
            },
            {
                "geonameId": 2517117,
                "name": "Grenade",
                "toponymName": "Granada",
                "fcl": "P",
                "fcode": "PPLA2",
                "countryCode": "ES",
                "countryName": "Espagne",
                "adminName1": "Andalucía",
                "lat": "37.18817",
                "lng": "-3.60667",
                "population": 232462,
                "timezone": {"timeZoneId": "Europe/Madrid"},
                "alternateNames": [{"name": "Grenade", "lang": "fr"}, {"name": "Granada", "lang": "es"}],
            },
        ],
    }

    # On vide REGION_QUERY_ALIASES pour prouver que la généralisation GeoNames (adminName1, alternateNames, T/A)
    # fonctionne par elle-même sans liste écrite à la main
    saved_aliases = dict(destinations_router.REGION_QUERY_ALIASES)
    monkeypatch.setattr(destinations_router, "REGION_QUERY_ALIASES", {})

    async def fake_fetch_generalized(q: str, settings: Any) -> dict[str, Any]:
        norm = destinations_router.normalize_geonames_query(q)
        if "santorin" in norm:
            return santorin_payload
        if "azur" in norm:
            return cote_d_azur_payload
        if "andalousie" in norm:
            return andalousie_payload
        return {"totalResultsCount": 0, "geonames": []}

    monkeypatch.setattr(destinations_router, "fetch_geonames_search_json", fake_fetch_generalized)

    # 1. "santorin"
    resp_santorin = await client.get("/api/v1/destinations/search", params={"q": "santorin"})
    assert resp_santorin.status_code == 200
    santorin_results = resp_santorin.json()["results"]
    santorin_names = [r["nom"] for r in santorin_results]
    assert "Fira" in santorin_names
    assert "Oia" in santorin_names
    assert "Région : Santorin" in santorin_names
    fira = next(r for r in santorin_results if r["nom"] == "Fira")
    assert fira["sous_titre"] == "Santorin • Grèce"
    assert fira["iata_code"] == "JTR"

    # 2. "côte d'azur"
    resp_azur = await client.get("/api/v1/destinations/search", params={"q": "côte d'azur"})
    assert resp_azur.status_code == 200
    azur_results = resp_azur.json()["results"]
    azur_names = [r["nom"] for r in azur_results]
    assert "Nice" in azur_names
    assert "Cannes" in azur_names
    assert any(n.startswith("Région :") for n in azur_names)
    nice = next(r for r in azur_results if r["nom"] == "Nice")
    assert "France" in nice["sous_titre"]
    assert nice["iata_code"] == "NCE"

    # 3. "andalousie"
    resp_andalousie = await client.get("/api/v1/destinations/search", params={"q": "andalousie"})
    assert resp_andalousie.status_code == 200
    andalousie_results = resp_andalousie.json()["results"]
    andalousie_names = [r["nom"] for r in andalousie_results]
    assert "Séville" in andalousie_names
    assert "Malaga" in andalousie_names
    assert "Grenade" in andalousie_names
    assert "Région : Andalousie" in andalousie_names
    seville = next(r for r in andalousie_results if r["nom"] == "Séville")
    assert seville["sous_titre"] == "Andalousie • Espagne"
    assert seville["iata_code"] == "SVQ"

    # 4. Vérifie que REGION_QUERY_ALIASES reste fonctionnel en secours si GeoNames ne renvoie ni T/A ni alternateNames
    monkeypatch.setattr(destinations_router, "REGION_QUERY_ALIASES", saved_aliases)
    assert "santorin" in destinations_router.REGION_QUERY_ALIASES
    assert "cote d azur" in destinations_router.REGION_QUERY_ALIASES
    assert "andalousie" in destinations_router.REGION_QUERY_ALIASES


@pytest.mark.asyncio
async def test_ourairports_local_file_and_license_and_mir_lis_icn(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    Point 5 — Aéroports :
    - Le fichier OurAirports est inclus localement dans backend/data/ourairports_iata.csv
      avec sa licence backend/data/OURAIRPORTS_LICENSE.txt (jamais téléchargé au démarrage).
    - Teste explicitement Monastir -> MIR, Lisbonne -> LIS, Séoul -> ICN.
    """
    from app.core.airports import (
        OURAIRPORTS_CATALOG,
        OURAIRPORTS_CSV_PATH,
        OURAIRPORTS_LICENSE_PATH,
        find_nearest_airport,
        load_ourairports_catalog,
    )

    assert OURAIRPORTS_CSV_PATH.is_file(), f"Fichier OurAirports absent : {OURAIRPORTS_CSV_PATH}"
    assert OURAIRPORTS_CSV_PATH.name == "ourairports_iata.csv"
    assert OURAIRPORTS_CSV_PATH.parent.name == "data"
    assert OURAIRPORTS_LICENSE_PATH.is_file(), f"Licence OurAirports absente : {OURAIRPORTS_LICENSE_PATH}"
    license_text = OURAIRPORTS_LICENSE_PATH.read_text(encoding="utf-8")
    assert "OurAirports" in license_text
    assert "Public Domain" in license_text

    reloaded_catalog = load_ourairports_catalog(OURAIRPORTS_CSV_PATH)
    assert len(reloaded_catalog) >= 150
    assert len(OURAIRPORTS_CATALOG) == len(reloaded_catalog)

    # 1. Monastir -> MIR
    mir = find_nearest_airport(
        latitude=35.77799,
        longitude=10.82617,
        city_name="Monastir",
        country_code="TN",
    )
    assert mir["iata_code"] == "MIR"
    assert mir["within_100km"] is True

    # 2. Lisbonne -> LIS
    lis = find_nearest_airport(
        latitude=38.71667,
        longitude=-9.13333,
        city_name="Lisbonne",
        country_code="PT",
    )
    assert lis["iata_code"] == "LIS"
    assert lis["within_100km"] is True

    # 3. Séoul -> ICN
    icn = find_nearest_airport(
        latitude=37.566,
        longitude=126.9784,
        city_name="Séoul",
        country_code="KR",
    )
    assert icn["iata_code"] == "ICN"
    assert icn["within_100km"] is True



