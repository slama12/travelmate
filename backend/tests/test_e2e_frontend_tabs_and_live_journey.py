from __future__ import annotations

from pathlib import Path
import re
import uuid

from httpx import AsyncClient
import pytest


def _normalize_frontend_api_base(raw_api_base: str) -> str:
    """Reproduit exactement la normalisation de API_BASE dans frontend/src/App.tsx."""
    step1 = re.sub(r"/api/v1/?$", "", raw_api_base.strip(), flags=re.IGNORECASE)
    return re.sub(r"/+$", "", step1)


def test_frontend_api_base_url_and_no_duplicate_api_v1_prefix() -> None:
    """
    Vérifie que :
    1. La normalisation de VITE_API_BASE_URL dans App.tsx empêche tout doublon /api/v1/api/v1
       même si VITE_API_BASE_URL contient accidentellement /api/v1.
    2. Aucun appel fetch dans le code source frontend ne produit de double préfixe /api/v1/api/v1.
    """
    for candidate in (
        "http://localhost:8000",
        "http://localhost:8000/",
        "http://localhost:8000/api/v1",
        "http://localhost:8000/api/v1/",
    ):
        normalized = _normalize_frontend_api_base(candidate)
        assert normalized == "http://localhost:8000"
        built_url = f"{normalized}/api/v1/accommodations/search"
        assert "/api/v1/api/v1" not in built_url

    repo_root = Path(__file__).resolve().parents[2]
    frontend_src = repo_root / "frontend" / "src"
    if frontend_src.exists():
        app_tsx = (frontend_src / "App.tsx").read_text(encoding="utf-8")
        envoi_c_tsx = (frontend_src / "EnvoiCScreens.tsx").read_text(encoding="utf-8")
        assert 'replace(/\\/api\\/v1\\/?$/i, "")' in app_tsx

        for content in (app_tsx, envoi_c_tsx):
            assert "/api/v1/api/v1" not in content


@pytest.mark.asyncio
async def test_e2e_all_six_frontend_tabs_and_complete_tokyo_journey_zero_404(
    client: AsyncClient,
) -> None:
    """
    Test de bout en bout couvrant les 6 onglets du frontend et le parcours complet :
    - Vérifie qu'aucune requête ne contient de doublon '/api/v1/api/v1' et qu'aucune ne renvoie 404.
    - Vérifie le parcours complet :
      1. Gestion du 401 (sans jeton / jeton invalide) puis Inscription d'un nouvel utilisateur + Connexion.
      2. Création d'un séjour pour Tokyo (HND).
      3. Recherche de vol CDG -> HND et réservation.
      4. Déblocage de la galerie des lieux de Tokyo et sélection d'un lieu.
      5. Planification d'une visite valide (synchronisée Google Calendar).
      6. Refus d'une visite hors de la fenêtre du séjour (OUTSIDE_STAY_WINDOW) avec créneaux suggérés.
      7. Refus d'une visite en chevauchement (VISIT_OVERLAP) avec créneaux suggérés.
      8. Chargement des onglets Hébergements & Restaurants, Transports sur place et Santé (/health).
    """
    recorded_calls: list[tuple[str, str, int]] = []

    async def tracked_request(method: str, path: str, **kwargs):
        # Simule la construction d'URL du frontend avec API_BASE normalisé
        api_base = _normalize_frontend_api_base("http://localhost:8000/api/v1")
        full_url = f"{api_base}{path}"
        assert "/api/v1/api/v1" not in full_url, f"Doublon de préfixe détecté dans {full_url}"

        resp = await client.request(method, path, **kwargs)
        recorded_calls.append((method, full_url, resp.status_code))
        assert resp.status_code != 404, (
            f"La requête {method} {full_url} a renvoyé 404 Not Found : {resp.text}"
        )
        return resp

    # -------------------------------------------------------------------------
    # ÉTAPE A : Vérification 401, Inscription, Connexion & /auth/me
    # -------------------------------------------------------------------------
    unauth_me = await tracked_request("GET", "/api/v1/auth/me")
    assert unauth_me.status_code == 401

    bad_token_me = await tracked_request(
        "GET",
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer jeton.jwt.invalide"},
    )
    assert bad_token_me.status_code == 401

    unique_email = f"voyageur.tokyo.{uuid.uuid4().hex[:8]}@travelmate.app"
    reg_resp = await tracked_request(
        "POST",
        "/api/v1/auth/register",
        json={
            "email": unique_email,
            "password": "TokyoPassword2026!",
            "full_name": "Camille Voyageur Tokyo",
            "preferred_style": "STANDARD",
        },
    )
    assert reg_resp.status_code == 201
    reg_data = reg_resp.json()
    assert reg_data["access_token"]
    assert reg_data["user"]["email"] == unique_email

    # Vérification de la connexion explicite (/auth/login) et du profil (/auth/me)
    login_resp = await tracked_request(
        "POST",
        "/api/v1/auth/login",
        json={"email": unique_email, "password": "TokyoPassword2026!"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {token}"}

    me_resp = await tracked_request("GET", "/api/v1/auth/me", headers=auth_headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["full_name"] == "Camille Voyageur Tokyo"

    # -------------------------------------------------------------------------
    # ONGLET 6 : Santé (/health)
    # -------------------------------------------------------------------------
    health_resp = await tracked_request("GET", "/health")
    assert health_resp.status_code == 200
    assert health_resp.json()["status"] == "ok"

    # -------------------------------------------------------------------------
    # ONGLET 1 : Destinations, Création d'un séjour Tokyo (HND), Vol CDG->HND & Réservation
    # -------------------------------------------------------------------------
    dest_resp = await tracked_request("GET", "/api/v1/destinations")
    assert dest_resp.status_code == 200
    destinations = dest_resp.json()
    tokyo = next(d for d in destinations if d["iata_code"] == "HND")

    trip_resp = await tracked_request(
        "POST",
        "/api/v1/trips",
        headers=auth_headers,
        json={
            "destination_id": tokyo["id"],
            "title": "Mon Séjour Complet à Tokyo",
            "travel_style": "STANDARD",
            "total_budget_planned": "2600.00",
            "currency": "EUR",
        },
    )
    assert trip_resp.status_code == 201
    trip = trip_resp.json()
    trip_id = trip["id"]

    trips_list_resp = await tracked_request("GET", "/api/v1/trips", headers=auth_headers)
    assert trips_list_resp.status_code == 200
    assert any(t["id"] == trip_id for t in trips_list_resp.json())

    # Avant réservation du vol, la galerie est verrouillée
    locked_gallery_resp = await tracked_request(
        "GET",
        f"/api/v1/places/trip/{trip_id}/gallery",
        headers=auth_headers,
    )
    assert locked_gallery_resp.status_code == 200
    assert locked_gallery_resp.json()["unlocked"] is False

    # Recherche de vols CDG -> HND
    flights_search_resp = await tracked_request(
        "GET",
        "/api/v1/flights/search",
        params={
            "origin_iata": "CDG",
            "destination_iata": "HND",
            "departure_date": "2026-11-10",
            "return_date": "2026-11-18",
            "travel_style": "STANDARD",
        },
    )
    assert flights_search_resp.status_code == 200
    offers = flights_search_resp.json()
    assert len(offers) >= 2
    chosen_offer = offers[0]
    assert chosen_offer["origin_iata"] == "CDG"
    assert chosen_offer["destination_iata"] == "HND"

    # Réservation du vol CDG -> HND
    book_resp = await tracked_request(
        "POST",
        "/api/v1/flights/book",
        headers=auth_headers,
        json={
            "trip_id": trip_id,
            "idempotency_key": f"idem-e2e-cdg-hnd-{trip_id[:8]}",
            "airline": chosen_offer["airline_name"],
            "flight_number_outbound": chosen_offer["flight_number_outbound"],
            "flight_number_inbound": chosen_offer["flight_number_inbound"],
            "origin_iata": chosen_offer["origin_iata"],
            "destination_iata": chosen_offer["destination_iata"],
            "departure_outbound_at": chosen_offer["departure_outbound_at"],
            "arrival_outbound_at": chosen_offer["arrival_outbound_at"],
            "departure_inbound_at": chosen_offer["departure_inbound_at"],
            "arrival_inbound_at": chosen_offer["arrival_inbound_at"],
            "price_amount": str(chosen_offer["price_amount"]),
            "currency": chosen_offer["currency"],
            "cabin_class": chosen_offer["cabin_class"],
        },
    )
    assert book_resp.status_code == 201
    booking = book_resp.json()
    assert booking["pnr_reference"].startswith("TM")
    assert booking["gmail_send_status"] == "SENT"
    assert booking["flight_status"] == "SCHEDULED"
    assert booking["transaction_steps"]["trip_dates_updated"] is True

    trip_bookings_resp = await tracked_request(
        "GET",
        f"/api/v1/flights/trip/{trip_id}",
        headers=auth_headers,
    )
    assert trip_bookings_resp.status_code == 200
    assert len(trip_bookings_resp.json()) == 1

    # -------------------------------------------------------------------------
    # ONGLET 2 : Hébergements & Restaurants proches (sans accommodation_type = Tout afficher)
    # -------------------------------------------------------------------------
    acc_tokyo_resp = await tracked_request(
        "GET",
        "/api/v1/accommodations/search",
        params={
            "lat": tokyo["latitude"],
            "lng": tokyo["longitude"],
            "radius_km": 12,
            "restaurant_radius_km": 5,
            "min_price": "50",
            "max_price": "2000",
        },
    )
    assert acc_tokyo_resp.status_code == 200
    acc_tokyo = acc_tokyo_resp.json()
    assert len(acc_tokyo) >= 2
    assert {a["type"] for a in acc_tokyo} == {"HOTEL", "AIRBNB"}

    # -------------------------------------------------------------------------
    # ONGLET 3 : Galerie des lieux débloquée après la réservation du vol
    # -------------------------------------------------------------------------
    unlocked_gallery_resp = await tracked_request(
        "GET",
        f"/api/v1/places/trip/{trip_id}/gallery",
        headers=auth_headers,
    )
    assert unlocked_gallery_resp.status_code == 200
    gallery = unlocked_gallery_resp.json()
    assert gallery["unlocked"] is True
    assert len(gallery["places"]) >= 3

    first_place = gallery["places"][0]
    second_place = gallery["places"][1]

    select_place_resp = await tracked_request(
        "POST",
        f"/api/v1/places/trip/{trip_id}/select",
        headers=auth_headers,
        json={"place_id": first_place["id"], "selected": True},
    )
    assert select_place_resp.status_code == 200
    assert any(
        p["id"] == first_place["id"] and p["is_selected_for_trip"] is True
        for p in select_place_resp.json()["places"]
    )

    # -------------------------------------------------------------------------
    # ONGLET 4 : Planification d'une visite, refus hors séjour et refus chevauchement
    # -------------------------------------------------------------------------
    schedule_resp = await tracked_request(
        "GET",
        f"/api/v1/itinerary/trip/{trip_id}",
        headers=auth_headers,
    )
    assert schedule_resp.status_code == 200
    assert schedule_resp.json()["destination_timezone"] == "Asia/Tokyo"

    # 1. Planification valide le 2026-11-11 de 10:00 à 11:30 (Asia/Tokyo)
    valid_visit_resp = await tracked_request(
        "POST",
        "/api/v1/itinerary/items",
        headers=auth_headers,
        json={
            "trip_id": trip_id,
            "place_id": first_place["id"],
            "visit_date": "2026-11-11",
            "local_start_time": "10:00",
            "duration_minutes": first_place["recommended_duration_min"],
            "transit_mode": "METRO",
            "notes": "Première visite à Tokyo",
        },
    )
    assert valid_visit_resp.status_code == 201
    created_visit = valid_visit_resp.json()
    assert created_visit["local_visit_date"] == "2026-11-11"
    assert created_visit["local_start_time"] == "10:00"
    assert created_visit["calendar_sync_status"] == "SYNCED"

    # 2. Refus d'une visite hors de la fenêtre du séjour (2026-11-25 > départ 2026-11-18)
    outside_stay_resp = await tracked_request(
        "POST",
        "/api/v1/itinerary/items",
        headers=auth_headers,
        json={
            "trip_id": trip_id,
            "place_id": second_place["id"],
            "visit_date": "2026-11-25",
            "local_start_time": "10:00",
            "duration_minutes": 90,
            "transit_mode": "METRO",
        },
    )
    assert outside_stay_resp.status_code == 422
    outside_detail = outside_stay_resp.json()["detail"]
    assert outside_detail["reason_code"] == "OUTSIDE_TRIP_WINDOW"
    assert "sort de la période du séjour" in outside_detail["message"]
    assert 2 <= len(outside_detail["suggested_slots"]) <= 3

    # 3. Refus d'un chevauchement (2026-11-11 à 10:30 chevauche la visite de 10:00 -> 11:30)
    overlap_resp = await tracked_request(
        "POST",
        "/api/v1/itinerary/items",
        headers=auth_headers,
        json={
            "trip_id": trip_id,
            "place_id": second_place["id"],
            "visit_date": "2026-11-11",
            "local_start_time": "10:30",
            "duration_minutes": 90,
            "transit_mode": "METRO",
        },
    )
    assert overlap_resp.status_code == 422
    overlap_detail = overlap_resp.json()["detail"]
    assert overlap_detail["reason_code"] == "OVERLAPPING_VISIT"
    assert "chevauche" in overlap_detail["message"]
    assert 2 <= len(overlap_detail["suggested_slots"]) <= 3

    # -------------------------------------------------------------------------
    # ONGLET 5 : Transports sur place & Transfert Aéroport -> Hébergement
    # -------------------------------------------------------------------------
    transports_resp = await tracked_request(
        "GET",
        f"/api/v1/transports/trip/{trip_id}",
        headers=auth_headers,
    )
    assert transports_resp.status_code == 200
    transports_data = transports_resp.json()
    assert transports_data["iata_code"] == "HND"
    assert len(transports_data["transit_passes"]) >= 1
    assert transports_data["airport_transfer"] is not None

    # Vérification globale finale : aucune requête 404 sur tout le parcours
    assert all(status != 404 for _, _, status in recorded_calls)


@pytest.mark.asyncio
async def test_live_docker_compose_backend_all_tabs_and_tokyo_scenario() -> None:
    """
    Test E2E réseau réel (TCP HTTP) contre le backend Docker Compose en cours d'exécution
    sur http://localhost:8000 (PostgreSQL + Redis réels).
    Échoue immédiatement si une requête d'onglet renvoie 404 ou si VITE_API_BASE_URL
    produit un doublon '/api/v1/api/v1'.
    """
    import os

    live_base = _normalize_frontend_api_base(
        os.getenv("VITE_API_BASE_URL", "http://localhost:8000")
    )
    assert live_base == "http://localhost:8000"
    assert "/api/v1" not in live_base

    candidate_bases = [live_base, "http://backend:8000"]
    reachable_base: str | None = None
    last_error: Exception | None = None
    for candidate in candidate_bases:
        try:
            async with AsyncClient(base_url=candidate, timeout=10.0) as probe_http:
                probe = await probe_http.get("/health")
                if probe.status_code == 200:
                    reachable_base = candidate
                    break
        except Exception as exc:
            last_error = exc

    assert reachable_base is not None, (
        f"Serveur HTTP live non joignable sur {candidate_bases}: {last_error}"
    )

    async with AsyncClient(base_url=reachable_base, timeout=15.0) as http:
        probe = await http.get("/health")
        assert probe.status_code == 200

        async def call_live(method: str, path: str, **kwargs):
            full_url = f"{live_base}{path}"
            assert "/api/v1/api/v1" not in full_url, f"Doublon /api/v1/api/v1 dans {full_url}"
            r = await http.request(method, path, **kwargs)
            assert r.status_code != 404, f"404 Not Found sur {method} {full_url}: {r.text}"
            return r

        # 1. Inscription d'un nouvel utilisateur sur le vrai PostgreSQL
        email = f"live.e2e.{uuid.uuid4().hex[:8]}@travelmate.app"
        reg = await call_live(
            "POST",
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "LivePassword2026!",
                "full_name": "E2E Live Runner",
                "preferred_style": "STANDARD",
            },
        )
        assert reg.status_code == 201
        jwt_token = reg.json()["access_token"]
        headers = {"Authorization": f"Bearer {jwt_token}"}

        # 2. Création d'un séjour Tokyo (HND)
        dests = (await call_live("GET", "/api/v1/destinations")).json()
        tokyo = next(d for d in dests if d["iata_code"] == "HND")

        trip = (
            await call_live(
                "POST",
                "/api/v1/trips",
                headers=headers,
                json={
                    "destination_id": tokyo["id"],
                    "title": "Séjour Live Docker Tokyo",
                    "travel_style": "STANDARD",
                    "total_budget_planned": "2500.00",
                    "currency": "EUR",
                },
            )
        ).json()
        trip_id = trip["id"]

        # 3. Recherche et réservation du vol CDG -> HND
        offers = (
            await call_live(
                "GET",
                "/api/v1/flights/search",
                params={
                    "origin_iata": "CDG",
                    "destination_iata": "HND",
                    "departure_date": "2026-11-10",
                    "return_date": "2026-11-18",
                    "travel_style": "STANDARD",
                },
            )
        ).json()
        offer = offers[0]

        booked = await call_live(
            "POST",
            "/api/v1/flights/book",
            headers=headers,
            json={
                "trip_id": trip_id,
                "idempotency_key": f"live-idem-{trip_id[:8]}",
                "airline": offer["airline_name"],
                "flight_number_outbound": offer["flight_number_outbound"],
                "flight_number_inbound": offer["flight_number_inbound"],
                "origin_iata": offer["origin_iata"],
                "destination_iata": offer["destination_iata"],
                "departure_outbound_at": offer["departure_outbound_at"],
                "arrival_outbound_at": offer["arrival_outbound_at"],
                "departure_inbound_at": offer["departure_inbound_at"],
                "arrival_inbound_at": offer["arrival_inbound_at"],
                "price_amount": str(offer["price_amount"]),
                "currency": offer["currency"],
                "cabin_class": offer["cabin_class"],
            },
        )
        assert booked.status_code == 201

        # 4. Chargement des 6 onglets sans aucun 404
        await call_live("GET", f"/api/v1/flights/trip/{trip_id}", headers=headers)
        acc_resp = await call_live(
            "GET",
            "/api/v1/accommodations/search",
            params={
                "lat": tokyo["latitude"],
                "lng": tokyo["longitude"],
                "radius_km": 12,
                "restaurant_radius_km": 5,
                "min_price": "50",
                "max_price": "2000",
            },
        )
        assert acc_resp.status_code == 200
        assert len(acc_resp.json()) >= 2

        gallery = (
            await call_live("GET", f"/api/v1/places/trip/{trip_id}/gallery", headers=headers)
        ).json()
        assert gallery["unlocked"] is True
        p1, p2 = gallery["places"][0], gallery["places"][1]

        await call_live(
            "POST",
            f"/api/v1/places/trip/{trip_id}/select",
            headers=headers,
            json={"place_id": p1["id"], "selected": True},
        )

        # 5. Planification valide, puis refus hors séjour, puis refus chevauchement
        ok_visit = await call_live(
            "POST",
            "/api/v1/itinerary/items",
            headers=headers,
            json={
                "trip_id": trip_id,
                "place_id": p1["id"],
                "visit_date": "2026-11-11",
                "local_start_time": "10:00",
                "duration_minutes": 90,
                "transit_mode": "METRO",
            },
        )
        assert ok_visit.status_code == 201

        err_outside = await call_live(
            "POST",
            "/api/v1/itinerary/items",
            headers=headers,
            json={
                "trip_id": trip_id,
                "place_id": p2["id"],
                "visit_date": "2026-11-25",
                "local_start_time": "10:00",
                "duration_minutes": 90,
                "transit_mode": "METRO",
            },
        )
        assert err_outside.status_code == 422
        assert err_outside.json()["detail"]["reason_code"] == "OUTSIDE_TRIP_WINDOW"

        err_overlap = await call_live(
            "POST",
            "/api/v1/itinerary/items",
            headers=headers,
            json={
                "trip_id": trip_id,
                "place_id": p2["id"],
                "visit_date": "2026-11-11",
                "local_start_time": "10:30",
                "duration_minutes": 90,
                "transit_mode": "METRO",
            },
        )
        assert err_overlap.status_code == 422
        assert err_overlap.json()["detail"]["reason_code"] == "OVERLAPPING_VISIT"

        await call_live("GET", f"/api/v1/itinerary/trip/{trip_id}", headers=headers)
        await call_live("GET", f"/api/v1/transports/trip/{trip_id}", headers=headers)


def _resolve_frontend_dir() -> Path:
    """
    Résout le répertoire frontend que le test s'exécute sur l'hôte
    ou dans le conteneur backend (monté en lecture seule sur /frontend).
    Aucun pytest.skip n'est autorisé.
    """
    candidates = [
        Path("/frontend"),
        Path(__file__).resolve().parents[2] / "frontend",
    ]
    for candidate in candidates:
        if candidate.exists() and (candidate / "src" / "App.tsx").exists():
            return candidate
    raise AssertionError(
        f"Répertoire frontend introuvable parmi {[str(c) for c in candidates]}"
    )


def _fetch_rendered_traveler_pages(frontend_dir: Path) -> dict:
    """
    Récupère le rendu réel des pages voyageur (HTML + texte visible réellement affiché)
    depuis le serveur Vite (http://frontend:5173/__rendered_pages en conteneur ou
    http://localhost:5173/__rendered_pages sur l'hôte) ou depuis le snapshot de build.
    """
    import json
    import os
    import httpx

    urls = []
    env_url = os.getenv("FRONTEND_INTERNAL_URL")
    if env_url:
        urls.append(f"{env_url.rstrip('/')}/__rendered_pages")
    urls.extend(
        [
            "http://frontend:5173/__rendered_pages",
            "http://localhost:5173/__rendered_pages",
        ]
    )

    last_err: Exception | None = None
    for url in urls:
        try:
            resp = httpx.get(url, timeout=15.0)
            if resp.status_code == 200:
                data = resp.json()
                if "pages" in data and "all_visible_text" in data:
                    return data
        except Exception as exc:
            last_err = exc

    rendered_json_path = frontend_dir / "dist" / "rendered_pages.json"
    if rendered_json_path.exists():
        return json.loads(rendered_json_path.read_text(encoding="utf-8"))

    raise AssertionError(
        f"Impossible de récupérer le rendu réel des pages depuis {urls}: {last_err}"
    )


def test_envoi_b_design_system_routes_and_zero_jargon() -> None:
    """
    Vérifie les exigences de DESIGN : ENVOI B à la fois sur le code source,
    le build de production et le texte réellement affiché au rendu des pages :
    - Composants réutilisables (Button, Card, Input, Select, Modal, Toast, Skeleton, Badge)
    - Routes React Router (/, /flights, /flights/confirmation, /login, /admin, etc.)
    - Vocabulaire voyageur obligatoire ("Référence de réservation", "Mes documents",
      "Réservation confirmée", "Choisir mes activités",
      "Cette destination n'est pas encore disponible en démonstration")
      vérifié dans le texte réellement affiché de chaque page rendue.
    - Zéro jargon technique ("Tester 2e clic", "Testeur Villes du Monde", "Post-Commit",
      "PWA", "Étape 3", "Seed", "Atomique", "PNR", "Coffre-fort", "Idempotence",
      "SIMULATED", "/health", "UTC", "latitude", "longitude")
      dans le texte réellement affiché sur l'ensemble des écrans voyageurs.
    """
    frontend_dir = _resolve_frontend_dir()

    app_tsx = (frontend_dir / "src" / "App.tsx").read_text(encoding="utf-8")
    ui_tsx = (frontend_dir / "src" / "components" / "ui" / "index.tsx").read_text(encoding="utf-8")
    tailwind_cfg = (frontend_dir / "tailwind.config.js").read_text(encoding="utf-8")

    for component_name in ("Button", "Card", "Input", "Select", "Modal", "ToastProvider", "Skeleton", "Badge"):
        assert component_name in ui_tsx

    assert "#FAF9F6" in tailwind_cfg
    assert "Inter" in tailwind_cfg

    for route_path in (
        'path="/"',
        'path="/flights"',
        'path="/flights/confirmation"',
        'path="/login"',
        'path="/admin"',
    ):
        assert route_path in app_tsx

    # 1. Vérification du rendu réel des pages voyageur (HTML + texte réellement affiché)
    rendered = _fetch_rendered_traveler_pages(frontend_dir)
    pages = rendered["pages"]
    all_visible_text = rendered["all_visible_text"]

    expected_rendered_routes = (
        "/",
        "/?unavailable=Séoul",
        "/flights",
        "/flights/confirmation",
        "/login",
        "/accommodations",
        "/activities",
        "/itinerary",
        "/trip",
        "/settings",
    )
    for route_key in expected_rendered_routes:
        assert route_key in pages, f"Route {route_key} absente du rendu des pages"
        assert len(pages[route_key]["visible_text"]) > 40

    # Vérification du texte réellement affiché par écran Envoi B
    assert "Où allez-vous ?" in pages["/"]["visible_text"]
    assert "Destinations populaires" in pages["/"]["visible_text"]
    assert (
        "Cette destination n'est pas encore disponible en démonstration"
        in pages["/?unavailable=Séoul"]["visible_text"]
    )
    assert "Moins cher" in pages["/flights"]["visible_text"]
    assert "Plus rapide" in pages["/flights"]["visible_text"]
    assert "Réserver" in pages["/flights"]["visible_text"]
    assert "Réservation confirmée" in pages["/flights/confirmation"]["visible_text"]
    assert "Référence de réservation" in pages["/flights/confirmation"]["visible_text"]
    assert "Mes documents" in pages["/flights/confirmation"]["visible_text"]
    assert "Choisir mes activités" in pages["/flights/confirmation"]["visible_text"]
    assert "Connexion" in pages["/login"]["visible_text"]

    # Vérification stricte anti-jargon sur le texte réellement affiché de TOUTES les pages voyageur
    forbidden_rendered_jargon = (
        "Tester 2e clic",
        "Testeur Villes du Monde",
        "Post-Commit",
        "PWA",
        "Étape 3",
        "ÉTAPE 3",
        "Seed",
        "Atomique",
        "PNR",
        "Coffre-fort",
        "Idempotence",
        "SIMULATED",
        "/health",
        "UTC",
        "latitude",
        "longitude",
        "moteur de validation",
        "Africa/Casablanca",
        "Asia/Makassar",
        "Europe/Lisbon",
        "Asia/Tokyo",
        "America/New_York",
        "Europe/Rome",
        "Africa/Cairo",
        "Asia/Seoul",
    )
    import re

    for route_key, page_payload in pages.items():
        visible_text = page_payload["visible_text"]
        for jargon in forbidden_rendered_jargon:
            assert jargon not in visible_text, (
                f"Jargon interdit '{jargon}' détecté dans le texte affiché de la page '{route_key}': "
                f"{visible_text}"
            )
        iso_dates_in_text = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", visible_text)
        assert not iso_dates_in_text, (
            f"Date brute AAAA-MM-JJ détectée dans le texte affiché de la page '{route_key}': "
            f"{iso_dates_in_text} dans '{visible_text}'"
        )

    assert not re.findall(r"\b\d{4}-\d{2}-\d{2}\b", all_visible_text), (
        f"Date brute AAAA-MM-JJ détectée dans all_visible_text: "
        f"{re.findall(r'\\b\\d{4}-\\d{2}-\\d{2}\\b', all_visible_text)}"
    )

    # Vérification également sur le build de production (dist/)
    dist_dir = frontend_dir / "dist"
    assert dist_dir.exists(), "Le dossier de build frontend/dist doit exister"
    dist_index = (dist_dir / "index.html").read_text(encoding="utf-8")
    assert "<div id=\"root\"></div>" in dist_index
    js_bundles = list((dist_dir / "assets").glob("*.js"))
    assert len(js_bundles) >= 1, "Aucun bundle JS trouvé dans frontend/dist/assets"
    built_js = "\n".join(p.read_text(encoding="utf-8") for p in js_bundles)
    for required_copy in (
        "Où allez-vous ?",
        "Cette destination n'est pas encore disponible en démonstration",
        "Moins cher",
        "Plus rapide",
        "Réservation confirmée",
        "Référence de réservation",
        "Mes documents",
        "Choisir mes activités",
    ):
        assert required_copy in built_js
        assert required_copy in all_visible_text

    for forbidden_in_bundle in (
        "Tester 2e clic",
        "Testeur Villes du Monde",
        "Post-Commit",
        "PWA • ÉTAPE 3",
        "moteur de validation",
    ):
        assert forbidden_in_bundle not in built_js
        assert forbidden_in_bundle not in app_tsx


def test_envoi_c_screens_progress_bar_and_no_provisional_navigation() -> None:
    """
    Vérifie les exigences de DESIGN : ENVOI C dans le code source ET dans le rendu réel des pages :
    1. Hébergement : liste de cartes + carte, bascule Liste / Carte sur mobile, filtres repliables,
       fiche avec restaurants proches, zéro saisie de coordonnées.
    2. À visiter : grille de grandes photos, bouton "Ajouter" ouvrant un petit panneau (jour, heure, durée préremplie),
       aperçu plein écran.
    3. Mon programme : UN JOUR à la fois, puces horizontales des jours, vue chronologique verticale,
       glisser-déposer, erreurs en français simple avec créneaux suggérés cliquables,
       bouton "Optimiser mon programme" avec aperçu avant validation.
    4. Mon voyage : page récapitulative (vol, hébergement, programme, transports sur place avec trajet aéroport -> hébergement, documents).
    5. Paramètres : devise, langue, style éco / standard / luxe.
    6. Navigation finale : barre de progression Destination > Vol > Hébergement > Activités > Programme,
       suppression de la navigation provisoire.
    """
    frontend_dir = _resolve_frontend_dir()

    app_tsx = (frontend_dir / "src" / "App.tsx").read_text(encoding="utf-8")
    envoi_c_tsx = (frontend_dir / "src" / "EnvoiCScreens.tsx").read_text(encoding="utf-8")

    # Suppression de la navigation et des écrans provisoires
    assert "ProvisionalLegacyScreens" not in app_tsx
    assert not (frontend_dir / "src" / "ProvisionalLegacyScreens.tsx").exists()

    # Barre de progression finale : Destination > Vol > Hébergement > Activités > Programme
    for step_label in ("Destination", "Vol", "Hébergement", "Activités", "Programme"):
        assert f'label: "{step_label}"' in app_tsx

    # Routes Envoi C
    for route_path in (
        'path="/accommodations"',
        'path="/activities"',
        'path="/itinerary"',
        'path="/trip"',
        'path="/settings"',
    ):
        assert route_path in app_tsx

    # Composants et éléments clés d'Envoi C dans le source
    for required_feature in (
        "AccommodationsScreen",
        "ActivitiesScreen",
        "ItineraryScreen",
        "MyTripSummaryScreen",
        "SettingsScreen",
        "Fiche & restaurants",
        "Restaurants proches accessibles à pied",
        "Optimiser mon programme",
        "Aperçu de votre programme optimisé",
        "Trajet aéroport → hébergement",
        "Devise d'affichage",
        "Langue de l'interface",
        "Style de voyage préféré",
    ):
        assert required_feature in envoi_c_tsx

    # Vérification du texte réellement affiché sur chaque écran Envoi C rendu
    rendered = _fetch_rendered_traveler_pages(frontend_dir)
    pages = rendered["pages"]

    for step_label in ("Destination", "Vol", "Hébergement", "Activités", "Programme"):
        assert step_label in pages["/"]["visible_text"]

    assert "Fiche & restaurants" in pages["/accommodations"]["visible_text"]
    assert "Jardin Majorelle" in pages["/activities"]["visible_text"]
    assert "Ajouter" in pages["/activities"]["visible_text"]
    assert "Optimiser mon programme" in pages["/itinerary"]["visible_text"]
    assert "Génère mon programme" in pages["/itinerary"]["visible_text"]
    assert "Trajet aéroport → hébergement" in pages["/trip"]["visible_text"]
    assert "Devise d'affichage" in pages["/settings"]["visible_text"]
    assert "Langue de l'interface" in pages["/settings"]["visible_text"]
    assert "Style de voyage préféré" in pages["/settings"]["visible_text"]



