from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.core.database import AsyncSession, get_db
from app.core.geo import (
    estimate_transit_duration_min,
    haversine_distance_km,
    haversine_distance_m,
    normalize_transit_mode,
)
from app.core.itinerary_validator import (
    ItineraryValidationEngine,
    ScheduledVisitSnapshot,
    ensure_utc,
    parse_local_slot_to_utc,
    to_destination_local,
)
from app.core.providers import get_provider_registry
from app.core.rbac import READ_ROLES, WRITE_ROLES, require_trip_access
from app.core.route_optimizer import OptimizablePlaceItem, RouteOptimizer
from app.models.entities import Destination, ItineraryItem, Place, Trip, TripStage, User
from app.modules.auth.router import get_current_user
from app.modules.itinerary.schemas import (
    ApplyOptimizationRequest,
    ItineraryItemCreateRequest,
    ItineraryItemResponse,
    ItineraryItemUpdateRequest,
    OptimizeItineraryPreviewResponse,
    OptimizeItineraryRequest,
    TripItineraryScheduleResponse,
)
from app.modules.trips.stages_service import (
    ensure_trip_stages,
    get_effective_departure_mode_for_stage,
    resolve_stage_for_visit,
)

router = APIRouter(prefix="/itinerary", tags=["Itinerary & Planning"])


async def _load_trip_and_destination(
    db: AsyncSession,
    trip_id: str,
    user_id: str,
    *,
    write: bool = False,
) -> tuple[Trip, Destination]:
    allowed = WRITE_ROLES if write else READ_ROLES
    trip, destination, _role = await require_trip_access(
        db, trip_id, user_id, allowed_roles=allowed
    )
    return trip, destination


async def _load_trip_items_with_places(
    db: AsyncSession, trip_id: str
) -> tuple[list[ItineraryItem], dict[str, Place]]:
    items = list(
        (
            await db.scalars(
                select(ItineraryItem)
                .where(ItineraryItem.trip_id == trip_id)
                .order_by(ItineraryItem.start_at.asc())
            )
        ).all()
    )
    place_ids = list({i.place_id for i in items})
    places_map: dict[str, Place] = {}
    if place_ids:
        places = list((await db.scalars(select(Place).where(Place.id.in_(place_ids)))).all())
        places_map = {p.id: p for p in places}
    return items, places_map


def _build_snapshots(
    items: list[ItineraryItem],
    places_map: dict[str, Place],
    destination_tz: str | None = None,
) -> list[ScheduledVisitSnapshot]:
    snapshots: list[ScheduledVisitSnapshot] = []
    for item in items:
        place = places_map.get(item.place_id)
        if not place:
            continue
        snapshots.append(
            ScheduledVisitSnapshot(
                item_id=item.id,
                place_id=place.id,
                place_name=place.name,
                latitude=place.latitude,
                longitude=place.longitude,
                start_at_utc=ensure_utc(item.start_at),
                end_at_utc=ensure_utc(item.end_at),
                transit_mode_to_next=normalize_transit_mode(item.transit_mode_to_next),
            )
        )
    return snapshots


async def _recompute_trip_day_transits(
    db: AsyncSession,
    trip_id: str,
    destination_tz: str,
    stages: list[TripStage] | None = None,
) -> tuple[list[ItineraryItem], dict[str, Place]]:
    """
    Recalcule l'ordre journalier (day_order_index) et les temps/distances de transport
    entre les visites consécutives d'une même journée locale et d'une même étape via le
    fournisseur d'itinéraires hybride (temps réel ou estimé Haversine).
    Au-delà de 1,8 km en ville, un trajet laissé par défaut en marche ('WALKING') bascule
    automatiquement en transport urbain ('METRO') pour éviter des estimations irréalistes
    (ex. 63 min à pied sur 4,7 km à New York au lieu de 17 min en métro).
    """
    registry = get_provider_registry()
    items, places_map = await _load_trip_items_with_places(db, trip_id)
    items.sort(key=lambda x: ensure_utc(x.start_at))

    stage_by_id: dict[str, TripStage] = {st.id: st for st in (stages or [])}

    by_stage_local_day: dict[tuple[str, date], list[ItineraryItem]] = {}
    for item in items:
        st = stage_by_id.get(item.stage_id or "") if item.stage_id else None
        item_tz = (st.timezone if st and st.timezone else destination_tz) or "UTC"
        loc_start = to_destination_local(ensure_utc(item.start_at), item_tz)
        item.visit_date = loc_start.date()
        group_key = (item.stage_id or "", loc_start.date())
        by_stage_local_day.setdefault(group_key, []).append(item)

    for _group_key, day_items in by_stage_local_day.items():
        day_items.sort(key=lambda x: ensure_utc(x.start_at))
        for idx, item in enumerate(day_items):
            item.day_order_index = idx + 1
            item.transit_mode_to_next = normalize_transit_mode(item.transit_mode_to_next)
            if idx + 1 < len(day_items):
                nxt = day_items[idx + 1]
                p_cur = places_map.get(item.place_id)
                p_nxt = places_map.get(nxt.place_id)
                if p_cur and p_nxt:
                    dist_km = haversine_distance_km(
                        p_cur.latitude, p_cur.longitude, p_nxt.latitude, p_nxt.longitude
                    )
                    mode_for_leg = normalize_transit_mode(nxt.transit_mode_to_next)
                    if mode_for_leg == "WALKING" and dist_km > 1.8:
                        mode_for_leg = "METRO"
                        nxt.transit_mode_to_next = "METRO"
                    leg = await registry.routing.compute_transit_leg(
                        p_cur.latitude,
                        p_cur.longitude,
                        p_nxt.latitude,
                        p_nxt.longitude,
                        mode=mode_for_leg,
                    )
                    item.transit_mode_to_next = mode_for_leg
                    item.transit_duration_to_next_min = int(leg["duration_minutes"])
                    item.transit_distance_meters = int(leg["distance_meters"])
                    item.transit_time_source = str(leg.get("source", "ESTIMATED")).upper()
                else:
                    item.transit_duration_to_next_min = 0
                    item.transit_distance_meters = 0
                    item.transit_time_source = (
                        "REAL" if registry.routing.mode == "real" and registry.routing.has_credentials() else "ESTIMATED"
                    )
            else:
                item.transit_duration_to_next_min = 0
                item.transit_distance_meters = 0
                item.transit_time_source = (
                    "REAL" if registry.routing.mode == "real" and registry.routing.has_credentials() else "ESTIMATED"
                )

    await db.commit()
    return items, places_map


async def _sync_item_with_google_calendar(
    db: AsyncSession,
    item: ItineraryItem,
    place: Place,
    destination_tz: str,
    *,
    action: str = "create",
    max_attempts: int = 2,
) -> bool:
    """
    Synchronise une visite avec Google Calendar via l'adaptateur hybride.
    Si l'appel Calendar échoue après `max_attempts` tentatives, la visite reste enregistrée
    avec le statut 'PENDING_SYNC' ('à synchroniser'), sans jamais annuler la visite.
    """
    registry = get_provider_registry()
    last_error: str | None = None
    start_utc = ensure_utc(item.start_at)
    end_utc = ensure_utc(item.end_at)
    description = item.notes or f"Visite planifiée via TravelMate : {place.name} ({place.category})"

    for _ in range(max_attempts):
        item.calendar_sync_attempts = (item.calendar_sync_attempts or 0) + 1
        try:
            if action == "update" and item.google_calendar_event_id:
                cal_res = await registry.calendar.update_visit_event(
                    calendar_id="primary",
                    event_id=item.google_calendar_event_id,
                    title=f"Visite : {place.name}",
                    location_name=place.name,
                    start_at=start_utc,
                    end_at=end_utc,
                    description=description,
                    timezone_name=destination_tz,
                )
            else:
                cal_res = await registry.calendar.create_visit_event(
                    calendar_id="primary",
                    title=f"Visite : {place.name}",
                    location_name=place.name,
                    start_at=start_utc,
                    end_at=end_utc,
                    description=description,
                    timezone_name=destination_tz,
                )
            item.google_calendar_event_id = cal_res.get("event_id") or item.google_calendar_event_id
            item.calendar_sync_status = "SYNCED"
            item.calendar_sync_error = None
            await db.commit()
            await db.refresh(item)
            return True
        except Exception as exc:
            last_error = str(exc)

    item.calendar_sync_status = "PENDING_SYNC"
    item.calendar_sync_error = last_error
    await db.commit()
    await db.refresh(item)
    return False


def _to_item_response(
    item: ItineraryItem,
    place: Place,
    destination_tz: str,
    *,
    stage: TripStage | None = None,
    transit_from_prev_min: int = 0,
    transit_from_prev_m: int = 0,
) -> ItineraryItemResponse:
    eff_tz = (stage.timezone if stage and stage.timezone else destination_tz) or "UTC"
    start_utc = ensure_utc(item.start_at)
    end_utc = ensure_utc(item.end_at)
    loc_start = to_destination_local(start_utc, eff_tz)
    loc_end = to_destination_local(end_utc, eff_tz)
    source = (getattr(item, "transit_time_source", None) or "ESTIMATED").upper()
    is_est = source != "REAL"
    return ItineraryItemResponse(
        id=item.id,
        trip_id=item.trip_id,
        stage_id=stage.id if stage else item.stage_id,
        stage_order_index=stage.order_index if stage else None,
        stage_city_name=stage.city_name if stage else None,
        place_id=item.place_id,
        place_name=place.name,
        place_category=place.category,
        place_is_outdoor=bool(place.is_outdoor),
        place_latitude=place.latitude,
        place_longitude=place.longitude,
        recommended_duration_min=place.recommended_duration_min,
        opening_hours=place.opening_hours or {},
        visit_date=loc_start.date(),
        start_at=start_utc,
        end_at=end_utc,
        local_visit_date=loc_start.strftime("%Y-%m-%d"),
        local_start_time=loc_start.strftime("%H:%M"),
        local_end_time=loc_end.strftime("%H:%M"),
        destination_timezone=eff_tz,
        duration_minutes=item.duration_minutes,
        transit_mode_to_next=normalize_transit_mode(item.transit_mode_to_next),
        transit_duration_to_next_min=item.transit_duration_to_next_min,
        transit_distance_meters=item.transit_distance_meters,
        transit_time_source=source,
        transit_is_estimated=is_est,
        transit_source_label="Temps réel" if not is_est else "Temps estimé",
        transit_from_previous_min=transit_from_prev_min,
        transit_from_previous_m=transit_from_prev_m,
        google_calendar_event_id=item.google_calendar_event_id,
        calendar_sync_status=item.calendar_sync_status,
        calendar_sync_attempts=item.calendar_sync_attempts,
        calendar_sync_error=item.calendar_sync_error,
        weather_warning=bool(getattr(item, "weather_warning", False)),
        weather_dismissed=bool(getattr(item, "weather_dismissed", False)),
        notes=item.notes,
        day_order_index=item.day_order_index,
    )


def _resolve_requested_start_utc(
    *,
    visit_date: date | None,
    local_start_time: str | None,
    start_at: datetime | None,
    duration_minutes: int,
    destination_tz: str,
) -> datetime:
    if visit_date is not None and local_start_time:
        start_utc, _ = parse_local_slot_to_utc(
            visit_date=visit_date,
            local_start_time_str=local_start_time,
            duration_minutes=duration_minutes,
            timezone_name=destination_tz,
        )
        return start_utc
    if start_at is not None:
        return ensure_utc(start_at)
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Veuillez renseigner soit (visit_date + local_start_time), soit start_at.",
    )


def _resolve_stage_context_for_visit(
    *,
    stages: list[TripStage],
    trip: Trip,
    default_tz: str,
    place: Place,
    visit_date: date | None = None,
    start_at: datetime | None = None,
    stage_id: str | None = None,
) -> tuple[TripStage | None, int, str, datetime | None, datetime | None, str | None, str | None]:
    """
    Détermine l'étape (TripStage), son fuseau horaire, ses bornes UTC d'arrivée/départ
    et ses modes de transport d'arrivée et de départ pour valider une visite.
    """
    if not stages:
        return None, 0, default_tz, trip.arrival_at, trip.departure_at, "VOL", "VOL"

    if len(stages) == 1:
        st0 = stages[0]
        tz0 = st0.timezone or default_tz or "UTC"
        # Pour un séjour mono-ville sans vol réservé (trip.arrival_at is None),
        # conserve le comportement d'origine (trip.arrival_at / trip.departure_at).
        arr_utc = trip.arrival_at if trip.arrival_at is not None else None
        dep_utc = trip.departure_at if trip.departure_at is not None else None
        arr_mode = st0.arrival_transport_mode or "VOL"
        dep_mode = get_effective_departure_mode_for_stage(stages, 0)
        return st0, 0, tz0, arr_utc, dep_utc, arr_mode, dep_mode

    # Multi-étapes : résolution par stage_id explicite, lieu + date, ou date / horodatage
    target_stage, stage_idx = resolve_stage_for_visit(
        stages,
        visit_date=visit_date,
        start_at_utc=ensure_utc(start_at) if start_at is not None else None,
        place=place,
        stage_id=stage_id,
    )
    # Si stage_id n'est pas fourni et que le lieu appartient uniquement à une autre étape du voyage,
    # on rattache la validation à l'étape de la ville du lieu (ce qui refusera proprement une date hors étape).
    if stage_id is None and target_stage is not None and place.destination_id != target_stage.destination_id:
        matching_place_stages = [
            (idx, st) for idx, st in enumerate(stages) if st.destination_id == place.destination_id
        ]
        if len(matching_place_stages) == 1:
            stage_idx, target_stage = matching_place_stages[0]

    assert target_stage is not None
    stage_tz = target_stage.timezone or default_tz or "UTC"
    arr_mode = target_stage.arrival_transport_mode or "VOL"
    dep_mode = get_effective_departure_mode_for_stage(stages, stage_idx)
    return (
        target_stage,
        stage_idx,
        stage_tz,
        target_stage.arrival_at,
        target_stage.departure_at,
        arr_mode,
        dep_mode,
    )


def _filter_items_for_stage_validation(
    existing_items: list[ItineraryItem],
    arg2: dict[str, Place] | TripStage | None,
    arg3: list[TripStage],
    arg4: TripStage | None = None,
) -> list[ItineraryItem]:
    if isinstance(arg2, dict):
        places_map: dict[str, Place] = arg2
        stages = arg3
        target_stage = arg4
    else:
        places_map = {}
        target_stage = arg2
        stages = arg3

    if len(stages) <= 1 or target_stage is None:
        return existing_items
    filtered: list[ItineraryItem] = []
    for it in existing_items:
        if it.stage_id == target_stage.id:
            filtered.append(it)
        elif it.stage_id is None:
            p = places_map.get(it.place_id)
            if p and p.destination_id == target_stage.destination_id:
                filtered.append(it)
            elif not places_map:
                if ensure_utc(target_stage.arrival_at) <= ensure_utc(it.start_at) <= ensure_utc(target_stage.departure_at):
                    filtered.append(it)
    return filtered


@router.get("/trip/{trip_id}", response_model=TripItineraryScheduleResponse)
async def get_trip_itinerary(
    trip_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TripItineraryScheduleResponse:
    registry = get_provider_registry()
    trip, destination = await _load_trip_and_destination(db, trip_id, current_user.id)
    dest_tz = destination.timezone or "UTC"
    stages = await ensure_trip_stages(db, trip)
    stage_by_id = {st.id: st for st in stages}
    first_stage = stages[0] if stages else None

    items, places_map = await _recompute_trip_day_transits(db, trip.id, dest_tz, stages=stages)

    responses: list[ItineraryItemResponse] = []
    days_grouped: dict[str, list[ItineraryItemResponse]] = {}

    if len(stages) > 1:
        for st in stages:
            cur_d = st.arrival_date
            while cur_d <= st.departure_date:
                days_grouped.setdefault(cur_d.isoformat(), [])
                cur_d += timedelta(days=1)
    elif trip.arrival_at and trip.departure_at:
        loc_arr = to_destination_local(ensure_utc(trip.arrival_at), dest_tz)
        loc_dep = to_destination_local(ensure_utc(trip.departure_at), dest_tz)
        cur_d = loc_arr.date()
        while cur_d <= loc_dep.date():
            days_grouped[cur_d.isoformat()] = []
            cur_d += timedelta(days=1)

    prev_by_stage_day: dict[tuple[str, str], tuple[ItineraryItem, Place]] = {}
    for item in items:
        place = places_map.get(item.place_id)
        if not place:
            continue
        item_stage = stage_by_id.get(item.stage_id or "") if item.stage_id else first_stage
        item_tz = (item_stage.timezone if item_stage and item_stage.timezone else dest_tz) or "UTC"
        loc_day_str = to_destination_local(ensure_utc(item.start_at), item_tz).strftime("%Y-%m-%d")
        stage_day_key = (item_stage.id if item_stage else "", loc_day_str)
        from_prev_min = 0
        from_prev_m = 0
        if stage_day_key in prev_by_stage_day:
            prev_item, _prev_place = prev_by_stage_day[stage_day_key]
            from_prev_min = prev_item.transit_duration_to_next_min
            from_prev_m = prev_item.transit_distance_meters
        resp_item = _to_item_response(
            item,
            place,
            dest_tz,
            stage=item_stage,
            transit_from_prev_min=from_prev_min,
            transit_from_prev_m=from_prev_m,
        )
        responses.append(resp_item)
        days_grouped.setdefault(loc_day_str, []).append(resp_item)
        prev_by_stage_day[stage_day_key] = (item, place)

    total_transit_min = sum(i.transit_duration_to_next_min for i in items)
    total_dist_m = sum(i.transit_distance_meters for i in items)
    pending_sync = sum(1 for i in items if i.calendar_sync_status != "SYNCED")
    has_real_leg = any(not r.transit_is_estimated for r in responses) or (
        registry.routing.mode == "real" and registry.routing.has_credentials()
    )

    arr_local_str = (
        to_destination_local(ensure_utc(trip.arrival_at), dest_tz).isoformat()
        if trip.arrival_at
        else None
    )
    dep_local_str = (
        to_destination_local(
            ensure_utc(trip.departure_at),
            stages[-1].timezone if stages else dest_tz,
        ).isoformat()
        if trip.departure_at
        else None
    )

    return TripItineraryScheduleResponse(
        trip_id=trip.id,
        destination_city=destination.city_name,
        destination_timezone=dest_tz,
        trip_arrival_utc=ensure_utc(trip.arrival_at) if trip.arrival_at else None,
        trip_departure_utc=ensure_utc(trip.departure_at) if trip.departure_at else None,
        trip_arrival_local=arr_local_str,
        trip_departure_local=dep_local_str,
        total_visits=len(responses),
        total_transit_minutes=total_transit_min,
        total_distance_meters=total_dist_m,
        routing_mode=registry.routing.mode,
        routing_source_label="Temps réel" if has_real_leg else "Temps estimé",
        pending_calendar_sync_count=pending_sync,
        items=responses,
        days=days_grouped,
    )


@router.post("/items", response_model=ItineraryItemResponse, status_code=status.HTTP_201_CREATED)
@router.post("/trip/{trip_id}/items", response_model=ItineraryItemResponse, status_code=status.HTTP_201_CREATED)
async def create_itinerary_item(
    payload: ItineraryItemCreateRequest,
    trip_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ItineraryItemResponse:
    """
    Planifie une nouvelle visite :
    1. Utilise la durée conseillée du lieu par défaut si duration_minutes n'est pas fourni.
    2. Résout l'étape du voyage correspondante (par stage_id, lieu et/ou date de visite).
    3. Valide la visite via ItineraryValidationEngine avec la fenêtre de visite, les tampons
       de transport (vol, train, bus, bateau, voiture) et le fuseau horaire de l'étape.
       En cas de refus, renvoie 422 avec un message clair en français et 2 à 3 créneaux libres suggérés.
    4. Stocke les horaires en UTC et synchronise avec Google Calendar.
    """
    resolved_trip_id = payload.trip_id or trip_id
    if not resolved_trip_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="L'identifiant du voyage (trip_id) est requis.",
        )
    trip, destination = await _load_trip_and_destination(
        db, resolved_trip_id, current_user.id, write=True
    )
    dest_tz = destination.timezone or "UTC"
    stages = await ensure_trip_stages(db, trip)

    place = await db.scalar(select(Place).where(Place.id == payload.place_id))
    if not place:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lieu à visiter introuvable.",
        )

    (
        target_stage,
        _stage_idx,
        stage_tz,
        stage_arr_utc,
        stage_dep_utc,
        arr_mode,
        dep_mode,
    ) = _resolve_stage_context_for_visit(
        stages=stages,
        trip=trip,
        default_tz=dest_tz,
        place=place,
        visit_date=payload.visit_date,
        start_at=payload.start_at,
        stage_id=payload.stage_id,
    )

    duration_min = payload.duration_minutes or place.recommended_duration_min or 120
    norm_mode = normalize_transit_mode(payload.transit_mode)
    start_utc = _resolve_requested_start_utc(
        visit_date=payload.visit_date,
        local_start_time=payload.local_start_time,
        start_at=payload.start_at,
        duration_minutes=duration_min,
        destination_tz=stage_tz,
    )
    end_utc = start_utc + timedelta(minutes=duration_min)

    existing_items, places_map = await _load_trip_items_with_places(db, trip.id)
    stage_existing_items = _filter_items_for_stage_validation(
        existing_items, places_map, stages, target_stage
    )
    snapshots = _build_snapshots(stage_existing_items, places_map)

    notes_lower = (payload.notes or "").lower()
    explicit_second_time = bool(
        payload.allow_duplicate
        or any(
            phrase in notes_lower
            for phrase in ("deuxième fois", "deuxieme fois", "2e fois", "2ème fois", "seconde fois")
        )
    )
    validation = ItineraryValidationEngine.validate_visit(
        trip_arrival_utc=stage_arr_utc,
        trip_departure_utc=stage_dep_utc,
        destination_tz_name=stage_tz,
        place_id=place.id,
        place_name=place.name,
        place_lat=place.latitude,
        place_lng=place.longitude,
        place_opening_hours=place.opening_hours,
        start_at_utc=start_utc,
        duration_minutes=duration_min,
        transit_mode=norm_mode,
        existing_visits=snapshots,
        allow_duplicate_place=explicit_second_time,
        arrival_transport_mode=arr_mode,
        departure_transport_mode=dep_mode,
    )
    if not validation.valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=validation.to_error_payload(),
        )

    loc_start = to_destination_local(start_utc, stage_tz)
    new_item = ItineraryItem(
        trip_id=trip.id,
        stage_id=target_stage.id if target_stage else None,
        place_id=place.id,
        visit_date=loc_start.date(),
        start_at=start_utc,
        end_at=end_utc,
        duration_minutes=duration_min,
        transit_mode_to_next=norm_mode,
        transit_duration_to_next_min=validation.transit_to_next_min,
        transit_distance_meters=validation.transit_to_next_m,
        calendar_sync_status="PENDING_SYNC",
        calendar_sync_attempts=0,
        notes=payload.notes,
        day_order_index=1,
    )
    db.add(new_item)
    await db.commit()
    await db.refresh(new_item)

    await _recompute_trip_day_transits(db, trip.id, dest_tz, stages=stages)
    await db.refresh(new_item)

    await _sync_item_with_google_calendar(
        db=db,
        item=new_item,
        place=place,
        destination_tz=stage_tz,
        action="create",
        max_attempts=2,
    )

    return _to_item_response(
        new_item,
        place,
        dest_tz,
        stage=target_stage,
        transit_from_prev_min=validation.transit_from_previous_min,
        transit_from_prev_m=validation.transit_from_previous_m,
    )


@router.patch("/items/{item_id}", response_model=ItineraryItemResponse)
async def update_or_move_itinerary_item(
    item_id: str,
    payload: ItineraryItemUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ItineraryItemResponse:
    """
    Déplace (glisser-déposer) ou modifie une visite existante.
    Chaque modification repasse intégralement par le moteur de validation (ItineraryValidationEngine)
    avec la fenêtre et le fuseau de l'étape concernée, et synchronise la mise à jour avec Google Calendar.
    """
    item = await db.scalar(select(ItineraryItem).where(ItineraryItem.id == item_id))
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Visite introuvable.",
        )

    trip, destination = await _load_trip_and_destination(
        db, item.trip_id, current_user.id, write=True
    )
    dest_tz = destination.timezone or "UTC"
    stages = await ensure_trip_stages(db, trip)
    place = await db.scalar(select(Place).where(Place.id == item.place_id))
    if not place:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lieu associé introuvable.",
        )

    duration_min = payload.duration_minutes or item.duration_minutes
    norm_mode = normalize_transit_mode(payload.transit_mode or item.transit_mode_to_next)

    (
        target_stage,
        _stage_idx,
        stage_tz,
        stage_arr_utc,
        stage_dep_utc,
        arr_mode,
        dep_mode,
    ) = _resolve_stage_context_for_visit(
        stages=stages,
        trip=trip,
        default_tz=dest_tz,
        place=place,
        visit_date=payload.visit_date,
        start_at=payload.start_at or item.start_at,
        stage_id=payload.stage_id or item.stage_id,
    )

    current_loc_start = to_destination_local(ensure_utc(item.start_at), stage_tz)
    if payload.start_at is not None:
        start_utc = ensure_utc(payload.start_at)
    elif payload.visit_date is not None or payload.local_start_time is not None:
        target_date = payload.visit_date or current_loc_start.date()
        target_time = payload.local_start_time or current_loc_start.strftime("%H:%M")
        start_utc, _ = parse_local_slot_to_utc(
            visit_date=target_date,
            local_start_time_str=target_time,
            duration_minutes=duration_min,
            timezone_name=stage_tz,
        )
    else:
        start_utc = ensure_utc(item.start_at)

    end_utc = start_utc + timedelta(minutes=duration_min)

    existing_items, places_map = await _load_trip_items_with_places(db, trip.id)
    stage_existing_items = _filter_items_for_stage_validation(
        existing_items, places_map, stages, target_stage
    )
    snapshots = _build_snapshots(stage_existing_items, places_map)

    validation = ItineraryValidationEngine.validate_visit(
        trip_arrival_utc=stage_arr_utc,
        trip_departure_utc=stage_dep_utc,
        destination_tz_name=stage_tz,
        place_id=place.id,
        place_name=place.name,
        place_lat=place.latitude,
        place_lng=place.longitude,
        place_opening_hours=place.opening_hours,
        start_at_utc=start_utc,
        duration_minutes=duration_min,
        transit_mode=norm_mode,
        existing_visits=snapshots,
        exclude_item_id=item.id,
        arrival_transport_mode=arr_mode,
        departure_transport_mode=dep_mode,
    )
    if not validation.valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=validation.to_error_payload(),
        )

    loc_start = to_destination_local(start_utc, stage_tz)
    if target_stage is not None:
        item.stage_id = target_stage.id
    item.visit_date = loc_start.date()
    item.start_at = start_utc
    item.end_at = end_utc
    item.duration_minutes = duration_min
    item.transit_mode_to_next = norm_mode
    if payload.notes is not None:
        item.notes = payload.notes

    await db.commit()
    await _recompute_trip_day_transits(db, trip.id, dest_tz, stages=stages)
    await db.refresh(item)

    await _sync_item_with_google_calendar(
        db=db,
        item=item,
        place=place,
        destination_tz=stage_tz,
        action="update",
        max_attempts=2,
    )

    return _to_item_response(
        item,
        place,
        dest_tz,
        stage=target_stage,
        transit_from_prev_min=validation.transit_from_previous_min,
        transit_from_prev_m=validation.transit_from_previous_m,
    )


@router.delete("/items/{item_id}")
async def delete_itinerary_item(
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Supprime une visite et synchronise la suppression dans Google Calendar."""
    item = await db.scalar(select(ItineraryItem).where(ItineraryItem.id == item_id))
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Visite introuvable.",
        )

    trip, destination = await _load_trip_and_destination(
        db, item.trip_id, current_user.id, write=True
    )
    dest_tz = destination.timezone or "UTC"
    event_id = item.google_calendar_event_id

    await db.delete(item)
    await db.commit()
    await _recompute_trip_day_transits(db, trip.id, dest_tz)

    calendar_deleted = False
    calendar_error: str | None = None
    if event_id:
        registry = get_provider_registry()
        for _ in range(2):
            try:
                await registry.calendar.delete_visit_event(calendar_id="primary", event_id=event_id)
                calendar_deleted = True
                calendar_error = None
                break
            except Exception as exc:
                calendar_error = str(exc)

    return {
        "deleted": True,
        "item_id": item_id,
        "google_calendar_event_id": event_id,
        "calendar_deleted": calendar_deleted if event_id else True,
        "calendar_error": calendar_error,
    }


@router.post("/items/{item_id}/sync-calendar", response_model=ItineraryItemResponse)
async def retry_item_calendar_sync(
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ItineraryItemResponse:
    """Relance la synchronisation Google Calendar d'une visite en statut 'PENDING_SYNC'."""
    item = await db.scalar(select(ItineraryItem).where(ItineraryItem.id == item_id))
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Visite introuvable.",
        )
    _trip, destination = await _load_trip_and_destination(
        db, item.trip_id, current_user.id, write=True
    )
    dest_tz = destination.timezone or "UTC"
    place = await db.scalar(select(Place).where(Place.id == item.place_id))
    if not place:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lieu introuvable.",
        )

    action = "update" if item.google_calendar_event_id else "create"
    await _sync_item_with_google_calendar(
        db=db,
        item=item,
        place=place,
        destination_tz=dest_tz,
        action=action,
        max_attempts=1,
    )
    return _to_item_response(item, place, dest_tz)


@router.post("/trip/{trip_id}/optimize", response_model=OptimizeItineraryPreviewResponse)
async def preview_optimized_itinerary(
    trip_id: str,
    payload: OptimizeItineraryRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OptimizeItineraryPreviewResponse:
    """
    Propose un nouveau planning optimisé (regroupement géographique par jour + ordre du plus proche voisin
    + temps de transport entre chaque étape).
    Rien n'est enregistré en base sans validation explicite par l'utilisateur via /apply-optimization.
    """
    trip, destination = await _load_trip_and_destination(
        db, trip_id, current_user.id, write=True
    )
    if not trip.arrival_at or not trip.departure_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Réservez d'abord votre billet d'avion pour définir la fenêtre du séjour avant d'optimiser.",
        )
    dest_tz = destination.timezone or "UTC"
    req = payload or OptimizeItineraryRequest()

    existing_items, existing_places_map = await _recompute_trip_day_transits(db, trip.id, dest_tz)
    current_transit_min = sum(i.transit_duration_to_next_min for i in existing_items)
    current_dist_m = sum(i.transit_distance_meters for i in existing_items)

    optimizable_items: list[OptimizablePlaceItem] = []

    if req.place_ids:
        places = list((await db.scalars(select(Place).where(Place.id.in_(req.place_ids)))).all())
        p_map = {p.id: p for p in places}
        for pid in req.place_ids:
            p = p_map.get(pid)
            if p:
                optimizable_items.append(
                    OptimizablePlaceItem(
                        place_id=p.id,
                        place_name=p.name,
                        category=p.category,
                        latitude=p.latitude,
                        longitude=p.longitude,
                        duration_minutes=p.recommended_duration_min or 120,
                        opening_hours=p.opening_hours,
                        preferred_transit_mode=req.default_transit_mode,
                    )
                )
    elif existing_items:
        for item in existing_items:
            p = existing_places_map.get(item.place_id)
            if p:
                optimizable_items.append(
                    OptimizablePlaceItem(
                        place_id=p.id,
                        place_name=p.name,
                        category=p.category,
                        latitude=p.latitude,
                        longitude=p.longitude,
                        duration_minutes=item.duration_minutes or p.recommended_duration_min or 120,
                        opening_hours=p.opening_hours,
                        preferred_transit_mode=req.default_transit_mode or item.transit_mode_to_next,
                        original_item_id=item.id,
                    )
                )
    elif trip.selected_place_ids:
        places = list(
            (await db.scalars(select(Place).where(Place.id.in_(trip.selected_place_ids)))).all()
        )
        p_map = {p.id: p for p in places}
        for pid in trip.selected_place_ids:
            p = p_map.get(pid)
            if p:
                optimizable_items.append(
                    OptimizablePlaceItem(
                        place_id=p.id,
                        place_name=p.name,
                        category=p.category,
                        latitude=p.latitude,
                        longitude=p.longitude,
                        duration_minutes=p.recommended_duration_min or 120,
                        opening_hours=p.opening_hours,
                        preferred_transit_mode=req.default_transit_mode,
                    )
                )

    if not optimizable_items:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Aucun lieu sélectionné ou planifié à optimiser sur ce voyage.",
        )

    try:
        proposal = RouteOptimizer.build_optimized_proposal(
            trip_arrival_utc=trip.arrival_at,
            trip_departure_utc=trip.departure_at,
            destination_tz_name=dest_tz,
            places=optimizable_items,
            default_transit_mode=req.default_transit_mode,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return OptimizeItineraryPreviewResponse(
        persisted=False,
        requires_user_confirmation=True,
        all_validated_by_engine=proposal["all_validated_by_engine"],
        destination_timezone=dest_tz,
        clusters_count=proposal["clusters_count"],
        total_places_scheduled=proposal["total_places_scheduled"],
        unscheduled_places=proposal["unscheduled_places"],
        current_total_transit_minutes=current_transit_min,
        current_total_distance_meters=current_dist_m,
        total_transit_minutes=proposal["total_transit_minutes"],
        total_distance_meters=proposal["total_distance_meters"],
        proposed_items=proposal["proposed_items"],
    )


@router.post("/trip/{trip_id}/apply-optimization", response_model=TripItineraryScheduleResponse)
async def apply_optimized_itinerary(
    trip_id: str,
    payload: ApplyOptimizationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TripItineraryScheduleResponse:
    """
    Enregistre le planning optimisé APRÈS validation explicite par l'utilisateur.
    Chaque étape proposée repasse obligatoirement par le moteur de validation (ItineraryValidationEngine)
    avant d'être persistée et synchronisée avec Google Calendar.
    """
    trip, destination = await _load_trip_and_destination(
        db, trip_id, current_user.id, write=True
    )
    dest_tz = destination.timezone or "UTC"

    if not payload.proposed_items:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La liste des créneaux optimisés à appliquer est vide.",
        )

    place_ids = list({slot.place_id for slot in payload.proposed_items})
    places = list((await db.scalars(select(Place).where(Place.id.in_(place_ids)))).all())
    places_map = {p.id: p for p in places}

    # 1. Validation intégrale de tout le planning proposé via ItineraryValidationEngine
    validated_snapshots: list[ScheduledVisitSnapshot] = []
    prepared_entries: list[tuple[Place, datetime, datetime, int, str]] = []

    for idx, slot in enumerate(payload.proposed_items):
        place = places_map.get(slot.place_id)
        if not place:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Lieu '{slot.place_id}' introuvable.",
            )
        norm_mode = normalize_transit_mode(slot.transit_mode_to_next)
        start_utc = _resolve_requested_start_utc(
            visit_date=slot.visit_date,
            local_start_time=slot.local_start_time,
            start_at=slot.start_at,
            duration_minutes=slot.duration_minutes,
            destination_tz=dest_tz,
        )
        end_utc = start_utc + timedelta(minutes=slot.duration_minutes)

        check = ItineraryValidationEngine.validate_visit(
            trip_arrival_utc=trip.arrival_at,
            trip_departure_utc=trip.departure_at,
            destination_tz_name=dest_tz,
            place_id=place.id,
            place_name=place.name,
            place_lat=place.latitude,
            place_lng=place.longitude,
            place_opening_hours=place.opening_hours,
            start_at_utc=start_utc,
            duration_minutes=slot.duration_minutes,
            transit_mode=norm_mode,
            existing_visits=validated_snapshots,
        )
        if not check.valid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=check.to_error_payload(),
            )

        validated_snapshots.append(
            ScheduledVisitSnapshot(
                item_id=f"apply-{idx + 1}",
                place_id=place.id,
                place_name=place.name,
                latitude=place.latitude,
                longitude=place.longitude,
                start_at_utc=start_utc,
                end_at_utc=end_utc,
                transit_mode_to_next=norm_mode,
            )
        )
        prepared_entries.append((place, start_utc, end_utc, slot.duration_minutes, norm_mode))

    # 2. Suppression des anciens éléments et création des nouveaux
    old_items, _ = await _load_trip_items_with_places(db, trip.id)
    for old in old_items:
        await db.delete(old)
    await db.flush()

    created_items: list[tuple[ItineraryItem, Place]] = []
    for order_idx, (place, start_utc, end_utc, duration_min, norm_mode) in enumerate(prepared_entries):
        loc_start = to_destination_local(start_utc, dest_tz)
        new_item = ItineraryItem(
            trip_id=trip.id,
            place_id=place.id,
            visit_date=loc_start.date(),
            start_at=start_utc,
            end_at=end_utc,
            duration_minutes=duration_min,
            transit_mode_to_next=norm_mode,
            calendar_sync_status="PENDING_SYNC",
            calendar_sync_attempts=0,
            day_order_index=order_idx + 1,
        )
        db.add(new_item)
        created_items.append((new_item, place))

    await db.commit()
    await _recompute_trip_day_transits(db, trip.id, dest_tz)

    # 3. Synchronisation Google Calendar de chaque étape
    for item_obj, place_obj in created_items:
        await db.refresh(item_obj)
        await _sync_item_with_google_calendar(
            db=db,
            item=item_obj,
            place=place_obj,
            destination_tz=dest_tz,
            action="create",
            max_attempts=2,
        )

    return await get_trip_itinerary(trip_id=trip.id, current_user=current_user, db=db)
