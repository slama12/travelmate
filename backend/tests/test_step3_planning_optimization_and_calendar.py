from typing import Any
from httpx import AsyncClient
import pytest

from app.core.providers import get_provider_registry


async def _auth_headers(client: AsyncClient) -> dict[str, str]:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "demo@travelmate.app", "password": "TravelMate2026!"},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _create_booked_trip(
    client: AsyncClient,
    headers: dict[str, str],
    city_name: str,
    *,
    origin_iata: str = "CDG",
    destination_iata: str = "HND",
    dep_out: str = "2026-10-10T06:00:00Z",
    arr_out: str = "2026-10-10T09:00:00Z",
    dep_in: str = "2026-10-14T20:00:00Z",
    arr_in: str = "2026-10-14T22:30:00Z",
    idem_suffix: str = "default",
) -> dict[str, Any]:
    dest_resp = await client.get("/api/v1/destinations")
    assert dest_resp.status_code == 200
    dest = next(d for d in dest_resp.json() if d["city_name"] == city_name)

    trip_resp = await client.post(
        "/api/v1/trips",
        headers=headers,
        json={
            "destination_id": dest["id"],
            "title": f"Séjour Étape 3 - {city_name} ({idem_suffix})",
            "travel_style": "STANDARD",
            "total_budget": 2800.0,
        },
    )
    assert trip_resp.status_code == 201
    trip = trip_resp.json()

    book_resp = await client.post(
        "/api/v1/flights/book",
        headers=headers,
        json={
            "trip_id": trip["id"],
            "idempotency_key": f"idem-step3-{city_name.lower()}-{idem_suffix}",
            "airline": "Air France",
            "flight_number_outbound": "AF274",
            "flight_number_inbound": "AF275",
            "origin_iata": origin_iata,
            "destination_iata": destination_iata,
            "departure_outbound_at": dep_out,
            "arrival_outbound_at": arr_out,
            "departure_inbound_at": dep_in,
            "arrival_inbound_at": arr_in,
            "price_amount": "420.00",
            "currency": "EUR",
            "cabin_class": "ECONOMY",
        },
    )
    assert book_resp.status_code == 201
    return trip


@pytest.mark.asyncio
async def test_planning_default_recommended_duration_drag_drop_and_calendar_sync(
    client: AsyncClient,
) -> None:
    """
    Règles 1, 5 & 8 :
    - La durée conseillée du lieu est utilisée par défaut si duration_minutes est omis.
    - Stockage en UTC et affichage dans le fuseau de la destination (Europe/Paris).
    - Synchronisation Google Calendar à la création, à la modification (glisser-déposer) et à la suppression.
    """
    headers = await _auth_headers(client)
    trip = await _create_booked_trip(
        client,
        headers,
        "Paris",
        origin_iata="FCO",
        destination_iata="CDG",
        dep_out="2026-06-10T04:00:00Z",
        arr_out="2026-06-10T06:00:00Z",  # 08:00 locale Paris (CEST UTC+2), tampon +2h -> 10:00 locale
        dep_in="2026-06-12T18:00:00Z",  # 20:00 locale Paris
        arr_in="2026-06-12T20:00:00Z",
        idem_suffix="plan-default",
    )

    places_resp = await client.get("/api/v1/places/city/Paris", headers=headers)
    assert places_resp.status_code == 200
    places = places_resp.json()["places"]
    louvre = next(p for p in places if "Louvre" in p["name"])

    # 1. Planification sans fournir duration_minutes -> doit prendre recommended_duration_min (180 min)
    create_resp = await client.post(
        "/api/v1/itinerary/items",
        headers=headers,
        json={
            "trip_id": trip["id"],
            "place_id": louvre["id"],
            "visit_date": "2026-06-10",
            "local_start_time": "11:00",
            "transit_mode": "METRO",
        },
    )
    assert create_resp.status_code == 201
    item = create_resp.json()
    assert item["duration_minutes"] == louvre["recommended_duration_min"] == 180
    assert item["local_visit_date"] == "2026-06-10"
    assert item["local_start_time"] == "11:00"
    assert item["local_end_time"] == "14:00"
    assert item["destination_timezone"] == "Europe/Paris"
    # En été à Paris (UTC+2), 11:00 locale = 09:00 UTC
    assert item["start_at"].startswith("2026-06-10T09:00:00")
    assert item["calendar_sync_status"] == "SYNCED"
    assert item["google_calendar_event_id"].startswith("sim-gcal-")

    # 2. Glisser-déposer (PATCH) vers 14:30 le lendemain -> re-validé et mis à jour sur Calendar
    move_resp = await client.patch(
        f"/api/v1/itinerary/items/{item['id']}",
        headers=headers,
        json={
            "visit_date": "2026-06-11",
            "local_start_time": "14:30",
            "duration_minutes": 120,
            "transit_mode": "WALKING",
        },
    )
    assert move_resp.status_code == 200
    moved = move_resp.json()
    assert moved["local_visit_date"] == "2026-06-11"
    assert moved["local_start_time"] == "14:30"
    assert moved["local_end_time"] == "16:30"
    assert moved["duration_minutes"] == 120
    assert moved["calendar_sync_status"] == "SYNCED"

    # 3. Suppression synchronisée avec Google Calendar
    del_resp = await client.delete(f"/api/v1/itinerary/items/{item['id']}", headers=headers)
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True
    assert del_resp.json()["calendar_deleted"] is True


@pytest.mark.asyncio
async def test_validation_engine_all_four_rules_and_suggested_free_slots(
    client: AsyncClient,
) -> None:
    """
    Règle 2 : Vérifie les 4 motifs précis de refus du moteur de validation :
    1) OUTSIDE_TRIP_WINDOW (hors fenêtre arrivée -> départ)
    2) OUTSIDE_OPENING_HOURS (hors horaires d'ouverture du lieu)
    3) OVERLAPPING_VISIT (chevauchement avec une autre visite)
    4) INSUFFICIENT_TRAVEL_TIME (temps de trajet WALKING / METRO / CAR insuffisant)
    Et vérifie qu'en cas de refus : message clair en français + 2 à 3 créneaux libres suggérés.
    """
    headers = await _auth_headers(client)
    trip = await _create_booked_trip(
        client,
        headers,
        "Paris",
        origin_iata="FCO",
        destination_iata="CDG",
        dep_out="2026-06-15T06:00:00Z",
        arr_out="2026-06-15T09:00:00Z",  # 11:00 locale Paris
        dep_in="2026-06-17T16:00:00Z",  # 18:00 locale Paris
        arr_in="2026-06-17T18:00:00Z",
        idem_suffix="val-4-rules",
    )

    places = (await client.get("/api/v1/places/city/Paris", headers=headers)).json()["places"]
    louvre = next(p for p in places if "Louvre" in p["name"])  # 09:00-18:00
    luxembourg = next(p for p in places if "Luxembourg" in p["name"])  # 07:30-20:30
    chartier = next(p for p in places if "Chartier" in p["name"])

    # Règle 2.1 : Hors de la fenêtre Trip.arrival_at -> Trip.departure_at (avant l'arrivée à 11:00)
    out_window_resp = await client.post(
        "/api/v1/itinerary/items",
        headers=headers,
        json={
            "trip_id": trip["id"],
            "place_id": louvre["id"],
            "visit_date": "2026-06-15",
            "local_start_time": "09:30",
            "duration_minutes": 120,
            "transit_mode": "METRO",
        },
    )
    assert out_window_resp.status_code == 422
    err_window = out_window_resp.json()["detail"]
    assert err_window["reason_code"] == "OUTSIDE_TRIP_WINDOW"
    assert "sort de la période du séjour" in err_window["message"]
    assert 2 <= len(err_window["suggested_slots"]) <= 3

    # Règle 2.2 : Hors des horaires d'ouverture du lieu (Louvre ferme à 18:00, créneau demandé 17:00-19:00)
    out_hours_resp = await client.post(
        "/api/v1/itinerary/items",
        headers=headers,
        json={
            "trip_id": trip["id"],
            "place_id": louvre["id"],
            "visit_date": "2026-06-15",
            "local_start_time": "17:00",
            "duration_minutes": 120,
            "transit_mode": "METRO",
        },
    )
    assert out_hours_resp.status_code == 422
    err_hours = out_hours_resp.json()["detail"]
    assert err_hours["reason_code"] == "OUTSIDE_OPENING_HOURS"
    assert "ouvert de" in err_hours["message"]
    assert 2 <= len(err_hours["suggested_slots"]) <= 3

    # Utilise directement le 1er créneau suggéré par le moteur pour planifier le Louvre !
    suggested_slot = err_hours["suggested_slots"][0]
    valid_louvre_resp = await client.post(
        "/api/v1/itinerary/items",
        headers=headers,
        json={
            "trip_id": trip["id"],
            "place_id": louvre["id"],
            "visit_date": suggested_slot["local_date"],
            "local_start_time": suggested_slot["local_start_time"],
            "duration_minutes": 120,
            "transit_mode": "METRO",
        },
    )
    assert valid_louvre_resp.status_code == 201
    louvre_item = valid_louvre_resp.json()

    # Règle 2.3 : Chevauchement avec la visite du Louvre
    overlap_resp = await client.post(
        "/api/v1/itinerary/items",
        headers=headers,
        json={
            "trip_id": trip["id"],
            "place_id": luxembourg["id"],
            "visit_date": louvre_item["local_visit_date"],
            "local_start_time": louvre_item["local_start_time"],
            "duration_minutes": 90,
            "transit_mode": "WALKING",
        },
    )
    assert overlap_resp.status_code == 422
    err_overlap = overlap_resp.json()["detail"]
    assert err_overlap["reason_code"] == "OVERLAPPING_VISIT"
    assert "chevauchement" in err_overlap["message"].lower()
    assert 2 <= len(err_overlap["suggested_slots"]) <= 3

    # Règle 2.4 : Temps de trajet insuffisant en mode WALKING juste à la minute de fin du Louvre
    insufficient_travel_resp = await client.post(
        "/api/v1/itinerary/items",
        headers=headers,
        json={
            "trip_id": trip["id"],
            "place_id": chartier["id"],
            "visit_date": louvre_item["local_visit_date"],
            "local_start_time": louvre_item["local_end_time"],  # 0 min de battement !
            "duration_minutes": 75,
            "transit_mode": "WALKING",
        },
    )
    assert insufficient_travel_resp.status_code == 422
    err_travel = insufficient_travel_resp.json()["detail"]
    assert err_travel["reason_code"] == "INSUFFICIENT_TRAVEL_TIME"
    assert "temps de trajet insuffisant" in err_travel["message"].lower()
    assert err_travel["conflict_details"]["transit_mode"] == "WALKING"
    assert err_travel["conflict_details"]["required_travel_minutes"] >= 15
    assert 2 <= len(err_travel["suggested_slots"]) <= 3


@pytest.mark.asyncio
async def test_timezone_boundary_cases_23h_arrival_single_day_and_dst_change(
    client: AsyncClient,
) -> None:
    """
    Règle 3 : Cas limites de fuseaux horaires :
    1) Vol qui arrive à 23h00 heure locale à Tokyo (Asia/Tokyo, UTC+9).
    2) Séjour d'un seul jour (arrivée 08h30 locale -> départ le soir même à 19h30 locale).
    3) Changement d'heure d'été -> hiver (DST Europe/Paris fin octobre 2026).
    """
    headers = await _auth_headers(client)

    # --- Cas limite A : Vol arrivant à 23h00 locale à Tokyo (14:00 UTC = 23:00 JST) ---
    trip_tokyo = await _create_booked_trip(
        client,
        headers,
        "Tokyo",
        origin_iata="CDG",
        destination_iata="HND",
        dep_out="2026-10-10T02:00:00Z",
        arr_out="2026-10-10T14:00:00Z",  # 23:00 locale Tokyo (le 10/10)
        dep_in="2026-10-13T01:00:00Z",  # 10:00 locale Tokyo (le 13/10)
        arr_in="2026-10-13T15:00:00Z",
        idem_suffix="tz-23h-tokyo",
    )
    tokyo_places = (await client.get("/api/v1/places/city/Tokyo", headers=headers)).json()["places"]
    sensoji = next(p for p in tokyo_places if "Senso-ji" in p["name"])  # 06:00-17:00

    # Tenter de visiter Senso-ji à 23:15 locale le soir de l'arrivée (23:05 locale) est refusé
    # car dans le tampon d'arrivée (+2h) et hors horaires, et les créneaux suggérés proposent le lendemain matin (2026-10-11)
    late_night_resp = await client.post(
        "/api/v1/itinerary/items",
        headers=headers,
        json={
            "trip_id": trip_tokyo["id"],
            "place_id": sensoji["id"],
            "visit_date": "2026-10-10",
            "local_start_time": "23:15",
            "duration_minutes": 90,
            "transit_mode": "METRO",
        },
    )
    assert late_night_resp.status_code == 422
    late_detail = late_night_resp.json()["detail"]
    assert late_detail["reason_code"] in ("OUTSIDE_TRIP_WINDOW", "OUTSIDE_OPENING_HOURS")
    assert len(late_detail["suggested_slots"]) >= 2
    assert late_detail["suggested_slots"][0]["local_date"] == "2026-10-11"

    # --- Cas limite B : Séjour d'un seul jour à Rome (arrivée 07:30 locale -> départ 19:30 locale le même jour) ---
    trip_one_day = await _create_booked_trip(
        client,
        headers,
        "Rome",
        origin_iata="CDG",
        destination_iata="FCO",
        dep_out="2026-05-20T03:30:00Z",
        arr_out="2026-05-20T05:30:00Z",  # 07:30 locale Rome (CEST UTC+2), tampon +2h -> 09:30 locale
        dep_in="2026-05-20T17:30:00Z",  # 19:30 locale Rome le MÊME jour, tampon -3h -> 16:30 locale
        arr_in="2026-05-20T19:35:00Z",
        idem_suffix="tz-oneday-rome",
    )
    rome_places = (await client.get("/api/v1/places/city/Rome", headers=headers)).json()["places"]
    colisee = next(p for p in rome_places if "Colisée" in p["name"])

    one_day_ok = await client.post(
        "/api/v1/itinerary/items",
        headers=headers,
        json={
            "trip_id": trip_one_day["id"],
            "place_id": colisee["id"],
            "visit_date": "2026-05-20",
            "local_start_time": "10:00",
            "duration_minutes": 120,
            "transit_mode": "METRO",
        },
    )
    assert one_day_ok.status_code == 201

    one_day_too_late = await client.post(
        "/api/v1/itinerary/items",
        headers=headers,
        json={
            "trip_id": trip_one_day["id"],
            "place_id": colisee["id"],
            "visit_date": "2026-05-20",
            "local_start_time": "18:30",  # Finit à 20:30 > départ 19:30 !
            "duration_minutes": 120,
            "transit_mode": "METRO",
        },
    )
    assert one_day_too_late.status_code == 422
    assert one_day_too_late.json()["detail"]["reason_code"] == "OUTSIDE_TRIP_WINDOW"

    # --- Cas limite C : Changement d'heure (DST Europe/Paris : passage UTC+2 -> UTC+1 le 25/10/2026) ---
    trip_dst = await _create_booked_trip(
        client,
        headers,
        "Paris",
        origin_iata="FCO",
        destination_iata="CDG",
        dep_out="2026-10-23T06:00:00Z",
        arr_out="2026-10-23T08:00:00Z",
        dep_in="2026-10-26T18:00:00Z",
        arr_in="2026-10-26T20:00:00Z",
        idem_suffix="tz-dst-paris",
    )
    paris_places = (await client.get("/api/v1/places/city/Paris", headers=headers)).json()["places"]
    louvre = next(p for p in paris_places if "Louvre" in p["name"])
    luxembourg = next(p for p in paris_places if "Luxembourg" in p["name"])

    # Samedi 24 octobre 2026 (heure d'été CEST = UTC+2) : 10:00 locale -> 08:00 UTC
    before_dst = await client.post(
        "/api/v1/itinerary/items",
        headers=headers,
        json={
            "trip_id": trip_dst["id"],
            "place_id": louvre["id"],
            "visit_date": "2026-10-24",
            "local_start_time": "10:00",
            "duration_minutes": 120,
            "transit_mode": "METRO",
        },
    )
    assert before_dst.status_code == 201
    assert before_dst.json()["start_at"].startswith("2026-10-24T08:00:00")

    # Dimanche 25 octobre 2026 (passage à l'heure d'hiver CET = UTC+1) : 10:00 locale -> 09:00 UTC
    after_dst = await client.post(
        "/api/v1/itinerary/items",
        headers=headers,
        json={
            "trip_id": trip_dst["id"],
            "place_id": luxembourg["id"],
            "visit_date": "2026-10-25",
            "local_start_time": "10:00",
            "duration_minutes": 90,
            "transit_mode": "WALKING",
        },
    )
    assert after_dst.status_code == 201
    assert after_dst.json()["start_at"].startswith("2026-10-25T09:00:00")


@pytest.mark.asyncio
async def test_route_optimization_preview_without_saving_and_validated_apply(
    client: AsyncClient,
) -> None:
    """
    Règle 4 :
    - Le bouton 'Optimiser' regroupe les lieux proches le même jour et les ordonne au plus proche voisin.
    - Rien n'est enregistré en base tant que l'utilisateur n'a pas validé.
    - Le planning proposé repasse intégralement par le moteur de validation lors de l'application.
    """
    headers = await _auth_headers(client)
    trip = await _create_booked_trip(
        client,
        headers,
        "Paris",
        origin_iata="FCO",
        destination_iata="CDG",
        dep_out="2026-07-01T06:00:00Z",
        arr_out="2026-07-01T08:00:00Z",
        dep_in="2026-07-04T19:00:00Z",
        arr_in="2026-07-04T21:00:00Z",
        idem_suffix="opt-paris",
    )

    places = (await client.get("/api/v1/places/city/Paris", headers=headers)).json()["places"]
    selected_ids = [p["id"] for p in places[:4]]

    # Sélectionne 4 lieux sur le séjour
    for pid in selected_ids:
        sel_resp = await client.post(
            f"/api/v1/places/trip/{trip['id']}/select",
            headers=headers,
            json={"place_id": pid, "selected": True},
        )
        assert sel_resp.status_code == 200

    # 1. Appel du bouton "Optimiser" (prévisualisation seule)
    opt_resp = await client.post(
        f"/api/v1/itinerary/trip/{trip['id']}/optimize",
        headers=headers,
        json={"place_ids": selected_ids},
    )
    assert opt_resp.status_code == 200
    preview = opt_resp.json()
    assert preview["persisted"] is False
    assert preview["requires_user_confirmation"] is True
    assert preview["all_validated_by_engine"] is True
    assert preview["total_places_scheduled"] == 4
    assert all(item["validated_by_engine"] is True for item in preview["proposed_items"])

    # Vérifie que RIEN n'a été enregistré en base avant validation par l'utilisateur
    schedule_before = await client.get(f"/api/v1/itinerary/trip/{trip['id']}", headers=headers)
    assert schedule_before.status_code == 200
    assert schedule_before.json()["total_visits"] == 0

    # 2. Validation par l'utilisateur -> enregistrement et synchronisation Google Calendar
    apply_resp = await client.post(
        f"/api/v1/itinerary/trip/{trip['id']}/apply-optimization",
        headers=headers,
        json={
            "proposed_items": [
                {
                    "place_id": item["place_id"],
                    "visit_date": item["visit_date"],
                    "local_start_time": item["local_start_time"],
                    "duration_minutes": item["duration_minutes"],
                    "transit_mode_to_next": item["transit_mode_to_next"],
                }
                for item in preview["proposed_items"]
            ]
        },
    )
    assert apply_resp.status_code == 200
    applied_schedule = apply_resp.json()
    assert applied_schedule["total_visits"] == 4
    assert all(i["calendar_sync_status"] == "SYNCED" for i in applied_schedule["items"])


@pytest.mark.asyncio
async def test_google_calendar_failure_keeps_visit_pending_sync_and_retries(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Règle 5 : Si l'appel Google Calendar échoue, la visite reste enregistrée avec un statut
    'PENDING_SYNC' ('à synchroniser') et une nouvelle tentative, sans annuler la visite.
    """
    headers = await _auth_headers(client)
    trip = await _create_booked_trip(
        client,
        headers,
        "Rome",
        origin_iata="CDG",
        destination_iata="FCO",
        dep_out="2026-08-10T06:00:00Z",
        arr_out="2026-08-10T08:00:00Z",
        dep_in="2026-08-13T18:00:00Z",
        arr_in="2026-08-13T20:00:00Z",
        idem_suffix="gcal-resilience",
    )
    rome_places = (await client.get("/api/v1/places/city/Rome", headers=headers)).json()["places"]
    pantheon = next(p for p in rome_places if "Panthéon" in p["name"] or "Colisée" in p["name"])

    registry = get_provider_registry()
    orig_create = registry.calendar.create_visit_event

    async def _failing_calendar(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("Panne API Google Calendar 503 simulée")

    monkeypatch.setattr(registry.calendar, "create_visit_event", _failing_calendar)

    create_resp = await client.post(
        "/api/v1/itinerary/items",
        headers=headers,
        json={
            "trip_id": trip["id"],
            "place_id": pantheon["id"],
            "visit_date": "2026-08-11",
            "local_start_time": "10:00",
            "duration_minutes": 90,
            "transit_mode": "WALKING",
        },
    )
    # La visite n'est PAS annulée malgré la panne Calendar
    assert create_resp.status_code == 201
    item = create_resp.json()
    assert item["calendar_sync_status"] == "PENDING_SYNC"
    assert item["calendar_sync_attempts"] == 2
    assert "Panne API Google Calendar 503" in (item["calendar_sync_error"] or "")
    assert item["google_calendar_event_id"] is None

    # Rétablissement du provider Calendar et relance de la synchronisation
    monkeypatch.setattr(registry.calendar, "create_visit_event", orig_create)
    retry_resp = await client.post(
        f"/api/v1/itinerary/items/{item['id']}/sync-calendar",
        headers=headers,
    )
    assert retry_resp.status_code == 200
    synced = retry_resp.json()
    assert synced["calendar_sync_status"] == "SYNCED"
    assert synced["calendar_sync_attempts"] == 3
    assert synced["calendar_sync_error"] is None
    assert synced["google_calendar_event_id"].startswith("sim-gcal-")


@pytest.mark.asyncio
async def test_local_transports_and_airport_to_accommodation_transfer(
    client: AsyncClient,
) -> None:
    """
    Règle 7 : Liens taxi/VTC, location de voiture, pass de transport par ville,
    et trajet aéroport -> hébergement (durée et prix estimés).
    """
    resp = await client.get("/api/v1/transports/city/Paris")
    assert resp.status_code == 200
    data = resp.json()
    assert data["city_name"] == "Paris"
    assert data["iata_code"] == "CDG"
    assert len(data["taxi_vtc_links"]) >= 1
    assert len(data["car_rental_links"]) >= 1
    assert len(data["transit_passes"]) >= 1

    transfer = data["airport_transfer"]
    assert transfer["airport_iata"] == "CDG"
    assert transfer["distance_km"] > 15.0
    assert len(transfer["options"]) == 3
    modes = {opt["mode"] for opt in transfer["options"]}
    assert modes == {"METRO", "VTC_TAXI", "CAR"}
    for opt in transfer["options"]:
        assert opt["estimated_duration_min"] >= 15
        assert float(opt["estimated_price_eur"]) > 0


@pytest.mark.asyncio
async def test_bug1_marrakech_trip_flight_search_and_booking_never_return_another_airport(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Bug 1 : Le séjour est à Marrakech (RAK).
    - Si un trip_id est fourni, la destination du séjour fait foi.
    - Une destination envoyée qui ne correspond pas au séjour renvoie une erreur 422 claire
      (pas de remplacement silencieux).
    - Sans destination_iata (ou avec RAK), la recherche, la réservation et l'email Gmail
      parlent exclusivement de CDG -> RAK.
    """
    headers = await _auth_headers(client)
    dests = (await client.get("/api/v1/destinations")).json()
    marrakech = next(d for d in dests if d["city_name"] == "Marrakech")
    assert marrakech["iata_code"] == "RAK"

    trip_resp = await client.post(
        "/api/v1/trips",
        headers=headers,
        json={
            "destination_id": marrakech["id"],
            "title": "Séjour Marrakech Ville Ocre",
            "travel_style": "STANDARD",
            "total_budget": 1800,
            "currency": "EUR",
        },
    )
    assert trip_resp.status_code == 201
    trip = trip_resp.json()

    # 1. Recherche avec trip_id et destination_iata="FCO" contradictoire -> erreur 422 claire
    search_mismatch = await client.get(
        "/api/v1/flights/search",
        headers=headers,
        params={
            "trip_id": trip["id"],
            "origin_iata": "CDG",
            "destination_iata": "FCO",
            "departure_date": "2026-11-10",
            "return_date": "2026-11-15",
            "travel_style": "STANDARD",
        },
    )
    assert search_mismatch.status_code == 422
    assert "RAK" in search_mismatch.json()["detail"]
    assert "FCO" in search_mismatch.json()["detail"]

    # 2. Recherche avec trip_id sans destination_iata -> utilise RAK et ne renvoie jamais un autre aéroport
    search_by_trip = await client.get(
        "/api/v1/flights/search",
        headers=headers,
        params={
            "trip_id": trip["id"],
            "origin_iata": "CDG",
            "departure_date": "2026-11-10",
            "return_date": "2026-11-15",
            "travel_style": "STANDARD",
        },
    )
    assert search_by_trip.status_code == 200
    offers = search_by_trip.json()
    assert isinstance(offers, list) and len(offers) >= 1
    for offer in offers:
        assert offer["destination_iata"] == "RAK"
        assert offer["destination_city"] == "Marrakech"
        assert offer["origin_iata"] == "CDG"
        assert offer["destination_iata"] != "FCO"

    chosen = offers[0]

    # 3. Réservation avec destination_iata="FCO" contradictoire sur un séjour Marrakech -> erreur 422 claire
    book_mismatch = await client.post(
        "/api/v1/flights/book",
        headers=headers,
        json={
            "trip_id": trip["id"],
            "idempotency_key": "idem-marrakech-mismatch-fco",
            "airline": chosen["airline_name"],
            "flight_number_outbound": chosen["flight_number_outbound"],
            "flight_number_inbound": chosen["flight_number_inbound"],
            "origin_iata": "CDG",
            "destination_iata": "FCO",
            "departure_outbound_at": chosen["departure_outbound_at"],
            "arrival_outbound_at": chosen["arrival_outbound_at"],
            "departure_inbound_at": chosen["departure_inbound_at"],
            "arrival_inbound_at": chosen["arrival_inbound_at"],
            "cabin_class": chosen["cabin_class"],
            "price_amount": str(chosen["price_amount"]),
            "currency": chosen["currency"],
        },
    )
    assert book_mismatch.status_code == 422
    assert "RAK" in book_mismatch.json()["detail"]

    # 4. Réservation valide CDG -> RAK : billet et email Gmail parlent exclusivement de CDG -> RAK
    captured_emails: list[dict[str, Any]] = []
    registry = get_provider_registry()
    orig_send = registry.gmail.send_booking_confirmation

    async def _spy_send_email(*args: Any, **kwargs: Any) -> dict[str, Any]:
        captured_emails.append({"args": args, "kwargs": kwargs})
        return await orig_send(*args, **kwargs)

    monkeypatch.setattr(registry.gmail, "send_booking_confirmation", _spy_send_email)

    book_resp = await client.post(
        "/api/v1/flights/book",
        headers=headers,
        json={
            "trip_id": trip["id"],
            "idempotency_key": "idem-marrakech-rak-bug1",
            "airline": chosen["airline_name"],
            "flight_number_outbound": chosen["flight_number_outbound"],
            "flight_number_inbound": chosen["flight_number_inbound"],
            "origin_iata": "CDG",
            "destination_iata": "RAK",
            "departure_outbound_at": chosen["departure_outbound_at"],
            "arrival_outbound_at": chosen["arrival_outbound_at"],
            "departure_inbound_at": chosen["departure_inbound_at"],
            "arrival_inbound_at": chosen["arrival_inbound_at"],
            "cabin_class": chosen["cabin_class"],
            "price_amount": str(chosen["price_amount"]),
            "currency": chosen["currency"],
        },
    )
    assert book_resp.status_code == 201
    booking = book_resp.json()
    assert booking["origin_iata"] == "CDG"
    assert booking["destination_iata"] == "RAK"
    assert len(captured_emails) == 1
    email_kwargs = captured_emails[0]["kwargs"]
    assert email_kwargs["origin_iata"] == "CDG"
    assert email_kwargs["destination_iata"] == "RAK"
    preview_text = str(booking.get("confirmation_email_preview") or "")
    assert "CDG" in preview_text and "RAK" in preview_text
    assert "FCO" not in preview_text


@pytest.mark.asyncio
async def test_bug2_accommodation_search_uses_trip_destination_zone_not_new_york(
    client: AsyncClient,
) -> None:
    """
    Bug 2 : Si lat/lng sont absents et qu'un séjour est connu (via trip_id ou séjour actif),
    la recherche d'hébergements utilise la zone de la destination du séjour
    (ex. Marrakech : 31.6295, -7.9811).
    """
    headers = await _auth_headers(client)
    dests = (await client.get("/api/v1/destinations")).json()
    marrakech = next(d for d in dests if d["city_name"] == "Marrakech")

    trip_resp = await client.post(
        "/api/v1/trips",
        headers=headers,
        json={
            "destination_id": marrakech["id"],
            "title": "Séjour Hébergements Marrakech",
            "travel_style": "STANDARD",
            "total_budget": 1500,
            "currency": "EUR",
        },
    )
    assert trip_resp.status_code == 201
    trip = trip_resp.json()

    # 1. Appel sans coordonnées (lat/lng absents) avec trip_id -> résout la zone de Marrakech
    resp_with_trip = await client.get(
        "/api/v1/accommodations/search",
        headers=headers,
        params={"trip_id": trip["id"], "radius_km": 12.0},
    )
    assert resp_with_trip.status_code == 200
    items_with_trip = resp_with_trip.json()
    assert isinstance(items_with_trip, list) and len(items_with_trip) >= 1
    names = [item["name"] for item in items_with_trip]
    assert any("Mamounia" in n or "Riad Patio Andalou" in n for n in names)
    assert all("New York" not in n and "SoHo" not in n and "Plaza" not in n for n in names)
    for item in items_with_trip:
        assert abs(item["latitude"] - marrakech["latitude"]) < 0.1
        assert abs(item["longitude"] - marrakech["longitude"]) < 0.1

    # 2. Appel sans coordonnées (lat/lng absents) ni trip_id -> utilise le séjour actif en base (Marrakech)
    resp_active_trip = await client.get(
        "/api/v1/accommodations/search",
        headers=headers,
        params={"radius_km": 12.0},
    )
    assert resp_active_trip.status_code == 200
    items_active = resp_active_trip.json()
    assert isinstance(items_active, list) and len(items_active) >= 1
    active_names = [item["name"] for item in items_active]
    assert any("Mamounia" in n or "Riad Patio Andalou" in n for n in active_names)
    assert all("New York" not in n and "SoHo" not in n and "Plaza" not in n for n in active_names)


@pytest.mark.asyncio
async def test_bug3_trip_window_arrival_plus_2h_and_departure_minus_3h_buffers_and_suggestions(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Bug 3 : Fenêtre du séjour :
    - début = arrivée aller + 2 h (configurable via TRIP_ARRIVAL_BUFFER_HOURS)
    - fin = départ retour - 3 h (configurable via TRIP_DEPARTURE_BUFFER_HOURS)
    - Les créneaux suggérés respectent strictement ces deux tampons.
    Tests :
    1) Visite dans le tampon d'arrivée (+2h) refusée (violation_phase == "ARRIVAL_BUFFER").
    2) Visite dans le tampon avant le retour (-3h) refusée (violation_phase == "DEPARTURE_BUFFER").
    3) Visite après le départ refusée (violation_phase == "AFTER_DEPARTURE").
    4) Tous les créneaux suggérés respectent [arrivée + 2h, départ - 3h].
    """
    from datetime import datetime, timedelta
    from app.core.config import get_settings

    headers = await _auth_headers(client)
    # Séjour à Marrakech (Africa/Casablanca = UTC+1) :
    # Arrivée aller : 2026-06-10T09:00:00Z (10:00 locale) -> tampon +2h = 11:00:00Z (12:00 locale)
    # Départ retour : 2026-06-12T17:00:00Z (18:00 locale) -> tampon -3h = 14:00:00Z (15:00 locale)
    arr_out_str = "2026-06-10T09:00:00Z"
    dep_in_str = "2026-06-12T17:00:00Z"
    trip = await _create_booked_trip(
        client,
        headers,
        "Marrakech",
        origin_iata="CDG",
        destination_iata="RAK",
        dep_out="2026-06-10T06:00:00Z",
        arr_out=arr_out_str,
        dep_in=dep_in_str,
        arr_in="2026-06-12T20:15:00Z",
        idem_suffix="buffers-marrakech",
    )

    places = (await client.get("/api/v1/places/city/Marrakech", headers=headers)).json()["places"]
    majorelle = next(p for p in places if "Majorelle" in p["name"])

    eff_start_utc = datetime.fromisoformat(arr_out_str.replace("Z", "+00:00")) + timedelta(hours=2)
    eff_end_utc = datetime.fromisoformat(dep_in_str.replace("Z", "+00:00")) - timedelta(hours=3)

    # 1. Visite dans le tampon d'arrivée : 10:30 locale (09:30 UTC), soit 30 min après l'atterrissage (< +2h) -> REFUSÉE
    in_arrival_buffer = await client.post(
        "/api/v1/itinerary/items",
        headers=headers,
        json={
            "trip_id": trip["id"],
            "place_id": majorelle["id"],
            "visit_date": "2026-06-10",
            "local_start_time": "10:30",
            "duration_minutes": 90,
            "transit_mode": "WALKING",
        },
    )
    assert in_arrival_buffer.status_code == 422
    arr_detail = in_arrival_buffer.json()["detail"]
    assert arr_detail["reason_code"] == "OUTSIDE_TRIP_WINDOW"
    assert arr_detail["conflict_details"]["violation_phase"] == "ARRIVAL_BUFFER"
    assert arr_detail["conflict_details"]["arrival_buffer_hours"] == 2.0
    assert len(arr_detail["suggested_slots"]) >= 2
    for slot in arr_detail["suggested_slots"]:
        slot_start = datetime.fromisoformat(slot["start_at"].replace("Z", "+00:00"))
        slot_end = datetime.fromisoformat(slot["end_at"].replace("Z", "+00:00"))
        assert slot_start >= eff_start_utc
        assert slot_end <= eff_end_utc

    # 2. Visite dans le tampon avant le retour : le 2026-06-12 de 14:00 à 16:00 locale (13:00 -> 15:00 UTC)
    # Le vol retour décolle à 18:00 locale (17:00 UTC), donc la fenêtre utile se ferme à 15:00 locale (14:00 UTC) -> REFUSÉE
    in_departure_buffer = await client.post(
        "/api/v1/itinerary/items",
        headers=headers,
        json={
            "trip_id": trip["id"],
            "place_id": majorelle["id"],
            "visit_date": "2026-06-12",
            "local_start_time": "14:00",
            "duration_minutes": 120,
            "transit_mode": "WALKING",
        },
    )
    assert in_departure_buffer.status_code == 422
    dep_buf_detail = in_departure_buffer.json()["detail"]
    assert dep_buf_detail["reason_code"] == "OUTSIDE_TRIP_WINDOW"
    assert dep_buf_detail["conflict_details"]["violation_phase"] == "DEPARTURE_BUFFER"
    assert dep_buf_detail["conflict_details"]["departure_buffer_hours"] == 3.0
    assert len(dep_buf_detail["suggested_slots"]) >= 2
    for slot in dep_buf_detail["suggested_slots"]:
        slot_start = datetime.fromisoformat(slot["start_at"].replace("Z", "+00:00"))
        slot_end = datetime.fromisoformat(slot["end_at"].replace("Z", "+00:00"))
        assert slot_start >= eff_start_utc
        assert slot_end <= eff_end_utc

    # 3. Visite après le départ retour : le 2026-06-12 de 17:30 à 19:00 locale (départ à 18:00 locale) -> REFUSÉE
    after_departure = await client.post(
        "/api/v1/itinerary/items",
        headers=headers,
        json={
            "trip_id": trip["id"],
            "place_id": majorelle["id"],
            "visit_date": "2026-06-12",
            "local_start_time": "17:30",
            "duration_minutes": 90,
            "transit_mode": "WALKING",
        },
    )
    assert after_departure.status_code == 422
    after_dep_detail = after_departure.json()["detail"]
    assert after_dep_detail["reason_code"] == "OUTSIDE_TRIP_WINDOW"
    assert after_dep_detail["conflict_details"]["violation_phase"] == "AFTER_DEPARTURE"
    assert len(after_dep_detail["suggested_slots"]) >= 2
    for slot in after_dep_detail["suggested_slots"]:
        slot_start = datetime.fromisoformat(slot["start_at"].replace("Z", "+00:00"))
        slot_end = datetime.fromisoformat(slot["end_at"].replace("Z", "+00:00"))
        assert slot_start >= eff_start_utc
        assert slot_end <= eff_end_utc

    # 4. Vérifie que la configuration dynamique des tampons est bien prise en compte
    settings = get_settings()
    monkeypatch.setattr(settings, "TRIP_ARRIVAL_BUFFER_HOURS", 3.0)
    # Avec un tampon d'arrivée porté à 3h, 12:30 locale (2h30 après l'arrivée à 10:00 locale) est refusé
    custom_buf_resp = await client.post(
        "/api/v1/itinerary/items",
        headers=headers,
        json={
            "trip_id": trip["id"],
            "place_id": majorelle["id"],
            "visit_date": "2026-06-10",
            "local_start_time": "12:30",
            "duration_minutes": 90,
            "transit_mode": "WALKING",
        },
    )
    assert custom_buf_resp.status_code == 422
    assert custom_buf_resp.json()["detail"]["conflict_details"]["violation_phase"] == "ARRIVAL_BUFFER"
    assert custom_buf_resp.json()["detail"]["conflict_details"]["arrival_buffer_hours"] == 3.0


@pytest.mark.asyncio
async def test_place_photos_match_landmarks_including_jardin_majorelle(
    client: AsyncClient,
) -> None:
    """
    Vérifie que chaque lieu possède sa propre photo authentique correspondant au lieu
    (en particulier le Jardin Majorelle à Marrakech), sans doublon entre lieux ni avec les hébergements.
    """
    headers = await _auth_headers(client)
    marrakech_resp = await client.get("/api/v1/places/city/Marrakech", headers=headers)
    assert marrakech_resp.status_code == 200
    marrakech_places = marrakech_resp.json()["places"]
    majorelle = next(p for p in marrakech_places if "Majorelle" in p["name"])
    assert len(majorelle["hero_photos"]) >= 1
    assert "majorelle" in majorelle["hero_photos"][0].lower()

    # Vérifie l'unicité de toutes les photos de lieux sur les 5 villes du seed (ou illustration neutre si pas de photo libre fiable)
    seen_photos: dict[str, str] = {}
    for city in ("Paris", "Tokyo", "Rome", "New York", "Marrakech"):
        resp = await client.get(f"/api/v1/places/city/{city}", headers=headers)
        assert resp.status_code == 200
        for place in resp.json()["places"]:
            if place["hero_photos"]:
                assert len(place["hero_photos"]) == 1
                photo_url = place["hero_photos"][0]
                assert photo_url.startswith("https://")
                assert photo_url not in seen_photos, (
                    f"Photo dupliquée entre « {place['name']} » et « {seen_photos[photo_url]} » : {photo_url}"
                )
                seen_photos[photo_url] = place["name"]
            else:
                assert place["photo_status"] == "Photo bientôt disponible"


