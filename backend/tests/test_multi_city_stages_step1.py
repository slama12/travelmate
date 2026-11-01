from __future__ import annotations

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSession
from app.core.security import create_access_token, hash_password
from app.models.entities import Destination, Place, TripMember, User


async def _auth_headers_for(
    db_session: AsyncSession, email: str, full_name: str = "Test Multi-Villes"
) -> dict[str, str]:
    user = await db_session.scalar(select(User).where(User.email == email))
    if not user:
        user = User(
            email=email,
            full_name=full_name,
            password_hash=hash_password("TestMultiCity123!"),
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
    token = create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_single_stage_trip_identical_to_existing_behavior(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    Vérifie qu'un séjour mono-ville existant continue à fonctionner à l'identique :
    un voyage à une seule étape (order_index=1) est automatiquement créé et synchronisé.
    """
    headers = await _auth_headers_for(db_session, "mono.stage@travelmate.fr")

    paris = await db_session.scalar(select(Destination).where(Destination.city_name == "Paris"))
    assert paris is not None
    paris_id = paris.id

    create_res = await client.post(
        "/api/v1/trips",
        headers=headers,
        json={
            "destination_id": paris_id,
            "origin_iata": "LYS",
            "arrival_at": "2026-10-10T09:00:00Z",
            "departure_at": "2026-10-14T18:00:00Z",
            "travel_style": "STANDARD",
            "total_budget_planned": 1400.0,
            "currency": "EUR",
        },
    )
    assert create_res.status_code == 201, create_res.text
    trip_data = create_res.json()
    trip_id = trip_data["id"]

    # Le voyage mono-ville possède exactement 1 étape ordonnée
    assert trip_data["stages_count"] == 1
    assert trip_data["is_multi_city"] is False
    assert len(trip_data["stages"]) == 1
    st0 = trip_data["stages"][0]
    assert st0["order_index"] == 1
    assert st0["city_name"] == "Paris"
    assert st0["country"] == "France"
    assert st0["timezone"] == "Europe/Paris"
    assert st0["nights"] == 4
    assert st0["arrival_transport_mode"] == "VOL"
    assert st0["arrival_buffer_hours"] == 2.0
    assert st0["departure_buffer_hours"] == 3.0

    # Réservation de vol classique (sans stage_id explicite) -> débloque l'étape 1 et la galerie
    book_res = await client.post(
        "/api/v1/flights/book",
        headers=headers,
        json={
            "trip_id": trip_id,
            "idempotency_key": "idem-mono-stage-1",
            "airline": "Air France",
            "flight_number_outbound": "AF7651",
            "flight_number_inbound": "AF7658",
            "origin_iata": "LYS",
            "destination_iata": "CDG",
            "departure_outbound_at": "2026-10-10T07:30:00Z",
            "arrival_outbound_at": "2026-10-10T09:00:00Z",
            "departure_inbound_at": "2026-10-14T18:00:00Z",
            "arrival_inbound_at": "2026-10-14T19:30:00Z",
            "price_amount": "195.00",
            "currency": "EUR",
        },
    )
    assert book_res.status_code == 201, book_res.text
    assert book_res.json()["stage_id"] == st0["id"]

    gal_res = await client.get(f"/api/v1/places/trip/{trip_id}/gallery", headers=headers)
    assert gal_res.status_code == 200, gal_res.text
    gal_data = gal_res.json()
    assert gal_data["unlocked"] is True
    assert gal_data["stage_id"] == st0["id"]
    assert len(gal_data["places"]) >= 3


@pytest.mark.asyncio
async def test_multi_city_stage_validation_rules_in_simple_french(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    Vérifie toutes les règles métier des étapes multi-villes avec messages d'erreur en français simple :
    - 1 à 10 étapes maximum,
    - Au moins 1 nuit par étape,
    - Étapes consécutives sans trou ni chevauchement,
    - Pas deux fois la même ville à la suite,
    - Dates cohérentes avec l'ordre.
    """
    headers = await _auth_headers_for(db_session, "rules.stage@travelmate.fr")

    # 1. Plus de 10 étapes -> refusé en français
    eleven_stages = []
    cur_d = date(2026, 7, 1)
    cities_cycle = [
        ("Paris", "France", 2988507, "Europe/Paris"),
        ("Rome", "Italie", 3169070, "Europe/Rome"),
        ("Marrakech", "Maroc", 2542997, "Africa/Casablanca"),
    ]
    for i in range(11):
        c_name, country, gid, tz = cities_cycle[i % 3]
        eleven_stages.append(
            {
                "order_index": i + 1,
                "geoname_id": gid,
                "city_name": c_name,
                "country": country,
                "arrival_date": cur_d.isoformat(),
                "nights": 1,
                "timezone": tz,
                "arrival_transport_mode": "VOL",
            }
        )
        cur_d = date.fromordinal(cur_d.toordinal() + 1)

    res_11 = await client.post(
        "/api/v1/trips",
        headers=headers,
        json={"origin_iata": "CDG", "stages": eleven_stages},
    )
    assert res_11.status_code == 422
    assert "10 étapes" in str(res_11.json())

    # 2. Moins d'une nuit (nights=0) -> refusé
    res_0_nights = await client.post(
        "/api/v1/trips",
        headers=headers,
        json={
            "origin_iata": "CDG",
            "stages": [
                {
                    "order_index": 1,
                    "city_name": "Paris",
                    "country": "France",
                    "arrival_date": "2026-07-01",
                    "nights": 0,
                    "timezone": "Europe/Paris",
                    "arrival_transport_mode": "VOL",
                }
            ],
        },
    )
    assert res_0_nights.status_code == 422

    # 3. Trou entre deux étapes (Paris 1-3 juillet, Rome 5 juillet) -> refusé en français
    res_gap = await client.post(
        "/api/v1/trips",
        headers=headers,
        json={
            "origin_iata": "CDG",
            "stages": [
                {
                    "order_index": 1,
                    "city_name": "Paris",
                    "country": "France",
                    "arrival_date": "2026-07-01",
                    "nights": 2,
                    "timezone": "Europe/Paris",
                    "arrival_transport_mode": "VOL",
                },
                {
                    "order_index": 2,
                    "city_name": "Rome",
                    "country": "Italie",
                    "arrival_date": "2026-07-05",
                    "nights": 2,
                    "timezone": "Europe/Rome",
                    "arrival_transport_mode": "TRAIN",
                },
            ],
        },
    )
    assert res_gap.status_code == 422
    assert "trou" in str(res_gap.json()["detail"]).lower()

    # 4. Chevauchement entre deux étapes (Paris 1-4 juillet, Rome 3 juillet) -> refusé en français
    res_overlap = await client.post(
        "/api/v1/trips",
        headers=headers,
        json={
            "origin_iata": "CDG",
            "stages": [
                {
                    "order_index": 1,
                    "city_name": "Paris",
                    "country": "France",
                    "arrival_date": "2026-07-01",
                    "nights": 3,
                    "timezone": "Europe/Paris",
                    "arrival_transport_mode": "VOL",
                },
                {
                    "order_index": 2,
                    "city_name": "Rome",
                    "country": "Italie",
                    "arrival_date": "2026-07-03",
                    "nights": 2,
                    "timezone": "Europe/Rome",
                    "arrival_transport_mode": "TRAIN",
                },
            ],
        },
    )
    assert res_overlap.status_code == 422
    assert "chevauchement" in str(res_overlap.json()["detail"]).lower()

    # 5. Deux fois la même ville à la suite (Paris -> Paris) -> refusé en français
    res_dup_city = await client.post(
        "/api/v1/trips",
        headers=headers,
        json={
            "origin_iata": "CDG",
            "stages": [
                {
                    "order_index": 1,
                    "geoname_id": 2988507,
                    "city_name": "Paris",
                    "country": "France",
                    "arrival_date": "2026-07-01",
                    "nights": 2,
                    "timezone": "Europe/Paris",
                    "arrival_transport_mode": "VOL",
                },
                {
                    "order_index": 2,
                    "geoname_id": 2988507,
                    "city_name": "Paris",
                    "country": "France",
                    "arrival_date": "2026-07-03",
                    "nights": 2,
                    "timezone": "Europe/Paris",
                    "arrival_transport_mode": "TRAIN",
                },
            ],
        },
    )
    assert res_dup_city.status_code == 422
    assert "deux fois la même ville" in str(res_dup_city.json()["detail"]).lower()


@pytest.mark.asyncio
async def test_three_stages_three_countries_timezones_boundary_visit_chat_voice_budget_and_transports(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    Teste de bout en bout un voyage à 3 étapes dans 3 pays avec changements de fuseau :
    - Étape 1 : Paris (France, Europe/Paris), 2 nuits (10 -> 12 nov 2026), arrivée VOL
    - Étape 2 : Marrakech (Maroc, Africa/Casablanca), 2 nuits (12 -> 14 nov 2026), arrivée TRAIN
    - Étape 3 : Tokyo (Japon, Asia/Tokyo), 3 nuits (14 -> 17 nov 2026), arrivée VOL
    Vérifie :
    - Fenêtre de visite par étape (avion +2h/-3h vs train tampon réduit +0.5h/-1.0h),
    - Validation d'une visite à la limite de deux étapes (12 nov et 14 nov),
    - Résolution de l'étape par la date dans le chat ET la voix,
    - Trajets inter-étapes (offre d'exemple OurAirports + bandeau pour VOL, comparateurs sans horaire/compagnie inventés pour TRAIN/BUS/BATEAU),
    - Déblocage de la galerie par étape après confirmation du trajet d'arrivée,
    - Budget cumulé avec détail par étape (stages_breakdown),
    - Réordonnancement d'étapes, suppression d'étape et RBAC.
    """
    headers = await _auth_headers_for(db_session, "three.stages@travelmate.fr")

    paris = await db_session.scalar(select(Destination).where(Destination.city_name == "Paris"))
    marrakech = await db_session.scalar(select(Destination).where(Destination.city_name == "Marrakech"))
    tokyo = await db_session.scalar(select(Destination).where(Destination.city_name == "Tokyo"))
    assert paris and marrakech and tokyo

    louvre = await db_session.scalar(
        select(Place).where(Place.destination_id == paris.id, Place.name.ilike("%Louvre%"))
    )
    majorelle = await db_session.scalar(
        select(Place).where(Place.destination_id == marrakech.id, Place.name.ilike("%Majorelle%"))
    )
    sensoji = await db_session.scalar(
        select(Place).where(Place.destination_id == tokyo.id, Place.name.ilike("%Senso%"))
    )
    assert louvre and majorelle and sensoji
    louvre_id = louvre.id
    majorelle_id = majorelle.id
    sensoji_name = sensoji.name

    create_res = await client.post(
        "/api/v1/trips",
        headers=headers,
        json={
            "origin_iata": "LYS",
            "travel_style": "STANDARD",
            "total_budget_planned": 3000.0,
            "currency": "EUR",
            "stages": [
                {
                    "order_index": 1,
                    "geoname_id": 2988507,
                    "city_name": "Paris",
                    "country": "France",
                    "arrival_date": "2026-11-10",
                    "nights": 2,
                    "timezone": "Europe/Paris",
                    "arrival_transport_mode": "VOL",
                    "arrival_time_local": "10:00",
                    "departure_time_local": "10:00",
                },
                {
                    "order_index": 2,
                    "geoname_id": 2542997,
                    "city_name": "Marrakech",
                    "country": "Maroc",
                    "arrival_date": "2026-11-12",
                    "nights": 2,
                    "timezone": "Africa/Casablanca",
                    "arrival_transport_mode": "TRAIN",
                    "arrival_time_local": "12:00",
                    "departure_time_local": "18:00",
                },
                {
                    "order_index": 3,
                    "geoname_id": 1850147,
                    "city_name": "Tokyo",
                    "country": "Japon",
                    "arrival_date": "2026-11-14",
                    "nights": 3,
                    "timezone": "Asia/Tokyo",
                    "arrival_transport_mode": "VOL",
                    "arrival_time_local": "10:00",
                    "departure_time_local": "20:00",
                },
            ],
        },
    )
    assert create_res.status_code == 201, create_res.text
    trip = create_res.json()
    trip_id = trip["id"]
    assert trip["stages_count"] == 3
    assert trip["is_multi_city"] is True

    stages = trip["stages"]
    st1, st2, st3 = stages[0], stages[1], stages[2]
    assert [s["country"] for s in stages] == ["France", "Maroc", "Japon"]
    assert [s["timezone"] for s in stages] == ["Europe/Paris", "Africa/Casablanca", "Asia/Tokyo"]

    # Vérifie les tampons : Étape 1 arrivée VOL (+2h) et départ vers Étape 2 en TRAIN (-1h)
    assert st1["arrival_buffer_hours"] == 2.0
    assert st1["departure_buffer_hours"] == 1.0
    # Étape 2 arrivée TRAIN (+0.5h) et départ vers Étape 3 en VOL (-3h)
    assert st2["arrival_buffer_hours"] == 0.5
    assert st2["departure_buffer_hours"] == 3.0
    # Étape 3 arrivée VOL (+2h) et départ final VOL (-3h)
    assert st3["arrival_buffer_hours"] == 2.0
    assert st3["departure_buffer_hours"] == 3.0

    # --- 4. Trajets inter-étapes ---
    transports_res = await client.get(f"/api/v1/trips/{trip_id}/transports", headers=headers)
    assert transports_res.status_code == 200, transports_res.text
    tr_data = transports_res.json()["stages_transports"]
    assert len(tr_data) == 3

    # Étape 1 (VOL LYS -> Paris) et Étape 3 (VOL Marrakech -> Tokyo) : offre d'exemple OurAirports + bandeau
    for vol_tr in (tr_data[0], tr_data[2]):
        assert vol_tr["arrival_transport_mode"] == "VOL"
        flight_ex = vol_tr["flight_example_offer"]
        assert flight_ex is not None
        assert flight_ex["distance_km"] > 0
        assert flight_ex["distance_source"] == "OurAirports"
        assert flight_ex["example_banner"] == "Offres d'exemple, prix indicatifs"
        assert flight_ex["has_invented_airline"] is False
        assert flight_ex["has_invented_flight_number"] is False
        assert flight_ex["has_invented_schedule"] is False

    # Étape 2 (TRAIN Paris -> Marrakech) : liens de comparateur uniquement, aucun horaire ni compagnie inventés
    train_tr = tr_data[1]
    assert train_tr["arrival_transport_mode"] == "TRAIN"
    assert train_tr["comparator_only"] is True
    assert train_tr["flight_example_offer"] is None
    assert len(train_tr["comparator_links"]) >= 2
    for link in train_tr["comparator_links"]:
        assert link["has_invented_schedule"] is False
        assert link["has_invented_company"] is False
        assert link["url"].startswith("https://")

    # --- 5. Déblocage de la galerie par étape ---
    # Avant confirmation du trajet d'arrivée, les galeries des étapes 1, 2 et 3 sont verrouillées
    gal1_locked = await client.get(
        f"/api/v1/places/trip/{trip_id}/gallery?stage_id={st1['id']}", headers=headers
    )
    assert gal1_locked.status_code == 200
    assert gal1_locked.json()["unlocked"] is False
    assert gal1_locked.json()["places"] == []

    # Sélection d'un lieu sur une étape verrouillée -> 403 Forbidden
    sel_locked = await client.post(
        f"/api/v1/places/trip/{trip_id}/select",
        headers=headers,
        json={"place_id": louvre_id, "stage_id": st1["id"], "selected": True},
    )
    assert sel_locked.status_code == 403

    # Débloque uniquement le trajet d'arrivée de l'étape 1 (Paris)
    unlock1_res = await client.post(
        f"/api/v1/trips/{trip_id}/stages/{st1['id']}/confirm-transport",
        headers=headers,
        json={"booking_reference": "AF-STAGE1", "cost_amount": 160.0, "currency": "EUR"},
    )
    assert unlock1_res.status_code == 200, unlock1_res.text

    # La galerie de l'étape 1 est maintenant débloquée, mais celle de l'étape 2 reste verrouillée !
    gal1_ok = await client.get(
        f"/api/v1/places/trip/{trip_id}/gallery?stage_id={st1['id']}", headers=headers
    )
    assert gal1_ok.status_code == 200
    assert gal1_ok.json()["unlocked"] is True
    assert gal1_ok.json()["city_name"] == "Paris"
    assert len(gal1_ok.json()["places"]) >= 3

    gal2_locked = await client.get(
        f"/api/v1/places/trip/{trip_id}/gallery?stage_id={st2['id']}", headers=headers
    )
    assert gal2_locked.status_code == 200
    assert gal2_locked.json()["unlocked"] is False
    assert gal2_locked.json()["places"] == []

    # Débloque les trajets d'arrivée des étapes 2 et 3
    await client.post(
        f"/api/v1/trips/{trip_id}/stages/{st2['id']}/confirm-transport",
        headers=headers,
        json={"booking_reference": "TRAIN-STAGE2", "cost_amount": 95.0, "currency": "EUR"},
    )
    await client.post(
        f"/api/v1/trips/{trip_id}/stages/{st3['id']}/confirm-transport",
        headers=headers,
        json={"booking_reference": "VOL-STAGE3", "cost_amount": 620.0, "currency": "EUR"},
    )
    gal2_ok = await client.get(
        f"/api/v1/places/trip/{trip_id}/gallery?stage_id={st2['id']}", headers=headers
    )
    assert gal2_ok.status_code == 200
    assert gal2_ok.json()["unlocked"] is True
    assert gal2_ok.json()["city_name"] == "Marrakech"

    # --- 3. Validation d'une visite à la limite de deux étapes (12 nov 2026) & tampon train réduit ---
    # Le 12 nov 2026 :
    # - Étape 2 (Marrakech) arrive en TRAIN à 12:00 locale, tampon train = +0.5h -> visites autorisées dès 12:30.
    # Une visite à Marrakech à 12:10 doit être refusée (dans le tampon d'arrivée train de 30 min) :
    visit_too_early_train = await client.post(
        f"/api/v1/itinerary/trip/{trip_id}/items",
        headers=headers,
        json={
            "place_id": majorelle_id,
            "visit_date": "2026-11-12",
            "local_start_time": "12:10",
            "duration_minutes": 90,
            "transit_mode_to_next": "WALK",
        },
    )
    assert visit_too_early_train.status_code == 422

    # La même visite à 12:30 (autorisée avec le tampon train de 0.5h, alors qu'en avion il faudrait 14:00) est ACCEPTÉE :
    visit_boundary_ok = await client.post(
        f"/api/v1/itinerary/trip/{trip_id}/items",
        headers=headers,
        json={
            "place_id": majorelle_id,
            "visit_date": "2026-11-12",
            "local_start_time": "12:30",
            "duration_minutes": 90,
            "transit_mode_to_next": "WALK",
        },
    )
    assert visit_boundary_ok.status_code == 201, visit_boundary_ok.text
    boundary_item = visit_boundary_ok.json()
    assert boundary_item["stage_id"] == st2["id"]
    assert boundary_item["stage_order_index"] == 2
    assert boundary_item["stage_city_name"] == "Marrakech"
    assert boundary_item["timezone"] == "Africa/Casablanca"

    # Sur ce même jour charnière (12 nov 2026), à la fin de l'étape 1 (Paris, départ train à 10:00, tampon départ train -1.0h -> 09:00),
    # une visite au Louvre de 09:00 à 10:00 dépasse la fenêtre de l'étape 1 et est refusée :
    visit_paris_after_cutoff = await client.post(
        f"/api/v1/itinerary/trip/{trip_id}/items",
        headers=headers,
        json={
            "place_id": louvre_id,
            "visit_date": "2026-11-12",
            "local_start_time": "09:00",
            "duration_minutes": 60,
            "transit_mode_to_next": "METRO",
        },
    )
    assert visit_paris_after_cutoff.status_code == 422

    # --- Chat et voix retrouvent l'étape d'une visite par la date (15 nov 2026 -> Étape 3 Tokyo, Asia/Tokyo) ---
    chat_res = await client.post(
        f"/api/v1/itinerary/trip/{trip_id}/chat",
        headers=headers,
        json={"message": f"Ajoute {sensoji_name} le 2026-11-15 à 10h00"},
    )
    assert chat_res.status_code == 200, chat_res.text
    last_chat_msg = chat_res.json()["messages"][-1]
    prop = last_chat_msg["proposed_action"]
    assert prop is not None
    assert prop["stage_id"] == st3["id"]
    assert prop["stage_order_index"] == 3
    assert prop["stage_city_name"] == "Tokyo"
    assert prop["stage_timezone"] == "Asia/Tokyo"
    assert prop["validated_by_engine"] is True

    # Et par la voix sur une date de l'étape 1 (11 nov 2026 -> Paris, Europe/Paris)
    voice_res = await client.post(
        f"/api/v1/itinerary/trip/{trip_id}/voice/command",
        headers=headers,
        json={"transcript": "Ajoute Musée du Louvre le 2026-11-11 à 14h00"},
    )
    assert voice_res.status_code == 200, voice_res.text
    voice_data = voice_res.json()
    v_prop = voice_data.get("proposed_action") or voice_data["message"]["proposed_action"]
    assert v_prop is not None
    assert v_prop["stage_id"] == st1["id"]
    assert v_prop["stage_order_index"] == 1
    assert v_prop["stage_city_name"] == "Paris"
    assert v_prop["stage_timezone"] == "Europe/Paris"

    # --- 5. Budget cumulé avec détail par étape ---
    exp_res = await client.post(
        f"/api/v1/budget/trip/{trip_id}/expenses",
        headers=headers,
        json={
            "stage_id": st2["id"],
            "category": "MEAL",
            "title": "Dîner place Jemaa el-Fna",
            "amount": 45.0,
            "currency": "EUR",
        },
    )
    assert exp_res.status_code == 201, exp_res.text
    budget_res = await client.get(f"/api/v1/budget/trip/{trip_id}", headers=headers)
    assert budget_res.status_code == 200, budget_res.text
    b_data = budget_res.json()
    assert float(b_data["total_spent"]) == pytest.approx(160.0 + 95.0 + 620.0 + 45.0)
    assert len(b_data["stages_breakdown"]) == 3
    sb1, sb2, sb3 = b_data["stages_breakdown"]
    assert sb1["city_name"] == "Paris" and float(sb1["spent_amount"]) == pytest.approx(160.0)
    assert sb2["city_name"] == "Marrakech" and float(sb2["spent_amount"]) == pytest.approx(140.0)
    assert sb3["city_name"] == "Tokyo" and float(sb3["spent_amount"]) == pytest.approx(620.0)

    # --- 6. Réordonnancement d'étapes, suppression d'étape et RBAC ---
    # Ajoute un lecteur (VIEWER) et vérifie qu'il peut lire les étapes mais pas les modifier
    viewer_headers = await _auth_headers_for(db_session, "viewer.stage@travelmate.fr")
    viewer_user = await db_session.scalar(select(User).where(User.email == "viewer.stage@travelmate.fr"))
    assert viewer_user is not None
    db_session.add(
        TripMember(
            trip_id=trip_id,
            user_id=viewer_user.id,
            role="VIEWER",
            invite_status="ACCEPTED",
        )
    )
    await db_session.commit()

    viewer_get = await client.get(f"/api/v1/trips/{trip_id}/stages", headers=viewer_headers)
    assert viewer_get.status_code == 200
    viewer_del = await client.delete(
        f"/api/v1/trips/{trip_id}/stages/{st3['id']}", headers=viewer_headers
    )
    assert viewer_del.status_code == 403

    # Réordonnancement par le propriétaire : [Paris (2n), Tokyo (3n), Marrakech (2n)]
    reorder_res = await client.put(
        f"/api/v1/trips/{trip_id}/stages/reorder",
        headers=headers,
        json={"stage_ids": [st1["id"], st3["id"], st2["id"]]},
    )
    assert reorder_res.status_code == 200, reorder_res.text
    reorder_body = reorder_res.json()
    reordered = reorder_body["stages"] if isinstance(reorder_body, dict) else reorder_body
    assert [s["city_name"] for s in reordered] == ["Paris", "Tokyo", "Marrakech"]
    assert [s["order_index"] for s in reordered] == [1, 2, 3]
    # Dates recalculées sans trou ni chevauchement : Paris 10->12, Tokyo 12->15, Marrakech 15->17
    assert reordered[0]["arrival_date"] == "2026-11-10" and reordered[0]["departure_date"] == "2026-11-12"
    assert reordered[1]["arrival_date"] == "2026-11-12" and reordered[1]["departure_date"] == "2026-11-15"
    assert reordered[2]["arrival_date"] == "2026-11-15" and reordered[2]["departure_date"] == "2026-11-17"

    # Suppression de l'étape 2 (Tokyo) : Marrakech recolle au 12 nov -> 14 nov
    del_res = await client.delete(
        f"/api/v1/trips/{trip_id}/stages/{st3['id']}", headers=headers
    )
    assert del_res.status_code == 200, del_res.text
    del_body = del_res.json()
    remaining = del_body["stages"] if isinstance(del_body, dict) else del_body
    assert len(remaining) == 2
    assert [s["city_name"] for s in remaining] == ["Paris", "Marrakech"]
    assert [s["order_index"] for s in remaining] == [1, 2]
    assert remaining[1]["arrival_date"] == "2026-11-12"
    assert remaining[1]["departure_date"] == "2026-11-14"
