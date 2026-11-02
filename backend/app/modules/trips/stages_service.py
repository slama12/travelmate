from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import quote_plus

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.airports import (
    are_airport_codes_equivalent,
    find_nearest_airport,
    haversine_distance_km,
    resolve_airport_record,
)
from app.core.itinerary_validator import (
    ItineraryValidationEngine,
    ensure_utc,
    get_arrival_buffer_hours_for_mode,
    get_departure_buffer_hours_for_mode,
    parse_local_slot_to_utc,
    resolve_destination_tz,
    to_destination_local,
)
from app. core.providers import get_provider_registry
from app.models.entities import (
    AccommodationBooking,
    BudgetItem,
    Destination,
    FlightBooking,
    ItineraryItem,
    Place,
    Trip,
    TripStage,
)
from app.models.enums import StageArrivalTransportMode, normalize_stage_transport_mode
from app.modules.destinations.router import (
    SEED_CITY_NAMES_LOWER,
    _resolve_or_create_destination_impl,
    normalize_geonames_query,
)
from app.modules.destinations.schemas import DestinationResolveRequest


def _default_stage_timestamps_utc(
    arrival_date: date,
    nights: int,
    tz_name: str,
    *,
    explicit_arrival_at: datetime | None = None,
    explicit_departure_at: datetime | None = None,
    arrival_time_local: str | None = None,
    departure_time_local: str | None = None,
) -> tuple[date, datetime, datetime]:
    """
    Calcule departure_date, arrival_at (UTC) et departure_at (UTC) pour une étape.
    Par défaut, l'arrivée sur l'étape est à 09:00 heure locale et le départ à 19:00 heure locale
    afin de laisser une journée complète de visite encadrée par les tampons de trajet.
    """
    dep_date = arrival_date + timedelta(days=nights)
    if explicit_arrival_at is not None:
        arr_utc = ensure_utc(explicit_arrival_at)
    else:
        arr_hm = (arrival_time_local or "09:00").strip()
        arr_utc, _ = parse_local_slot_to_utc(arrival_date, arr_hm, 60, tz_name)

    if explicit_departure_at is not None:
        dep_utc = ensure_utc(explicit_departure_at)
    else:
        dep_hm = (departure_time_local or "19:00").strip()
        dep_utc, _ = parse_local_slot_to_utc(dep_date, dep_hm, 60, tz_name)

    if dep_utc <= arr_utc:
        dep_utc = arr_utc + timedelta(hours=max(12, nights * 24))
    return dep_date, arr_utc, dep_utc



def _same_city_identity(stage_a: dict[str, Any], stage_b: dict[str, Any]) -> bool:
    gid_a = stage_a.get("geoname_id")
    gid_b = stage_b.get("geoname_id")
    if gid_a is not None and gid_b is not None:
        return int(gid_a) == int(gid_b)

    dest_a = stage_a.get("destination_id")
    dest_b = stage_b.get("destination_id")
    if dest_a and dest_b and str(dest_a) == str(dest_b):
        return True

    city_a = normalize_geonames_query(str(stage_a.get("city_name") or ""))
    city_b = normalize_geonames_query(str(stage_b.get("city_name") or ""))
    if not city_a or not city_b or city_a != city_b:
        return False

    iso_a = str(stage_a.get("country_code_iso2") or "").strip().upper()
    iso_b = str(stage_b.get("country_code_iso2") or "").strip().upper()
    if iso_a and iso_b and iso_a != "XX" and iso_b != "XX":
        return iso_a == iso_b
    return True


def validate_stages_rules(stages_specs: list[dict[str, Any]]) -> None:
    """
    Valide l'ensemble des règles métier d'un voyage multi-villes avec messages en français simple :
    1. Entre 1 et 10 étapes.
    2. Au moins 1 nuit par étape.
    3. Dates cohérentes avec l'ordre des étapes.
    4. Étapes consécutives sans trou ni chevauchement.
    5. Pas deux fois la même ville à la suite.
    """
    count = len(stages_specs)
    if count < 1 or count > 10:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "reason_code": "INVALID_STAGE_COUNT",
                "message": "Un voyage doit comprendre entre 1 et 10 étapes.",
            },
        )

    for idx, spec in enumerate(stages_specs):
        step_num = idx + 1
        city_label = str(spec.get("city_name") or f"Étape {step_num}")

        arr_date = spec.get("arrival_date")
        if isinstance(arr_date, str) and len(arr_date) >= 10:
            try:
                arr_date = date.fromisoformat(arr_date[:10])
                spec["arrival_date"] = arr_date
            except ValueError:
                arr_date = None
        if not isinstance(arr_date, date):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "reason_code": "INVALID_STAGE_DATE",
                    "message": f"La date d'arrivée de l'étape {step_num} ({city_label}) est manquante ou invalide.",
                },
            )

        explicit_dep_date = spec.get("departure_date")
        if isinstance(explicit_dep_date, str) and len(explicit_dep_date) >= 10:
            try:
                explicit_dep_date = date.fromisoformat(explicit_dep_date[:10])
                spec["departure_date"] = explicit_dep_date
            except ValueError:
                explicit_dep_date = None

        if isinstance(explicit_dep_date, date) and explicit_dep_date <= arr_date:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "reason_code": "INCONSISTENT_STAGE_DATES",
                    "message": (
                        f"Les dates de l'étape {step_num} ({city_label}) sont incohérentes : "
                        "la date de départ doit être postérieure à la date d'arrivée (au moins 1 nuit sur place)."
                    ),
                },
            )

        raw_nights = spec.get("nights")
        if raw_nights is None and isinstance(explicit_dep_date, date):
            nights = (explicit_dep_date - arr_date).days
            spec["nights"] = nights
        else:
            nights = int(raw_nights if raw_nights is not None else 0)

        if nights < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "reason_code": "INVALID_STAGE_NIGHTS",
                    "message": (
                        f"Chaque étape doit compter au moins 1 nuit sur place "
                        f"(étape {step_num} à {city_label} : {nights} nuit)."
                    ),
                },
            )

        try:
            spec["arrival_transport_mode"] = normalize_stage_transport_mode(
                spec.get("arrival_transport_mode")
            )
            if spec.get("departure_transport_mode") is not None:
                spec["departure_transport_mode"] = normalize_stage_transport_mode(
                    spec.get("departure_transport_mode")
                )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "reason_code": "INVALID_TRANSPORT_MODE",
                    "message": str(exc),
                },
            ) from exc

        expected_dep_date = arr_date + timedelta(days=nights)
        if isinstance(explicit_dep_date, date) and explicit_dep_date != expected_dep_date:
            nights = (explicit_dep_date - arr_date).days
            spec["nights"] = nights
            expected_dep_date = explicit_dep_date
        spec["departure_date"] = expected_dep_date

        if idx > 0:
            prev = stages_specs[idx - 1]
            prev_city = str(prev.get("city_name") or f"Étape {idx}")
            prev_arr: date = prev["arrival_date"]
            prev_dep: date = prev["departure_date"]

            # Règle : Pas deux fois la même ville à la suite
            if _same_city_identity(prev, spec):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "reason_code": "CONSECUTIVE_DUPLICATE_CITY",
                        "message": (
                            f"Vous ne pouvez pas mettre deux fois la même ville à la suite "
                            f"({city_label} aux étapes {idx} et {step_num})."
                        ),
                    },
                )

            # Règle : Dates cohérentes avec l'ordre
            if arr_date <= prev_arr:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "reason_code": "INCONSISTENT_STAGE_DATES",
                        "message": (
                            f"Les dates des étapes doivent suivre l'ordre du voyage : "
                            f"l'étape {step_num} ({city_label}, arrivée le {arr_date.isoformat()}) "
                            f"ne peut pas commencer avant ou le même jour que l'étape {idx} "
                            f"({prev_city}, arrivée le {prev_arr.isoformat()})."
                        ),
                    },
                )

            # Règle : Étapes consécutives sans trou ni chevauchement
            if arr_date < prev_dep:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "reason_code": "STAGE_DATE_OVERLAP",
                        "message": (
                            f"Les étapes doivent se suivre sans trou ni chevauchement : "
                            f"l'étape {step_num} ({city_label}) commence le {arr_date.isoformat()} "
                            f"alors que l'étape {idx} ({prev_city}) se termine le {prev_dep.isoformat()} "
                            "(chevauchement de dates)."
                        ),
                    },
                )
            if arr_date > prev_dep:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "reason_code": "STAGE_DATE_GAP",
                        "message": (
                            f"Les étapes doivent se suivre sans trou ni chevauchement : "
                            f"l'étape {idx} ({prev_city}) se termine le {prev_dep.isoformat()} "
                            f"mais l'étape {step_num} ({city_label}) ne commence que le {arr_date.isoformat()} "
                            "(jours vides entre les deux étapes)."
                        ),
                    },
                )


async def resolve_stage_destination(
    db: AsyncSession,
    spec: dict[str, Any],
) -> Destination:
    """
    Résout ou crée la Destination SQLAlchemy correspondant à une étape (par destination_id
    ou par ville GeoNames : geoname_id, city_name, country_name, country_code_iso2, timezone).
    """
    dest_id = spec.get("destination_id")
    if dest_id:
        dest = await db.scalar(select(Destination).where(Destination.id == str(dest_id)))
        if dest is not None:
            return dest

    geoname_id = spec.get("geoname_id")
    if geoname_id is not None:
        dest = await db.scalar(select(Destination).where(Destination.geoname_id == int(geoname_id)))
        if dest is not None:
            return dest

    city_name = str(spec.get("city_name") or "").strip()
    if not city_name:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Destination de l'étape introuvable (indiquez destination_id ou city_name).",
        )

    resolve_req = DestinationResolveRequest(
        geoname_id=int(geoname_id) if geoname_id is not None else None,
        city_name=city_name,
        country_name=str(spec.get("country_name") or "Monde"),
        country_code_iso2=str(spec.get("country_code_iso2") or "XX")[:2],
        timezone=str(spec.get("timezone") or "UTC"),
        latitude=float(spec["latitude"]) if spec.get("latitude") is not None else None,
        longitude=float(spec["longitude"]) if spec.get("longitude") is not None else None,
        iata_code=spec.get("iata_code"),
    )
    resolved_schema = await _resolve_or_create_destination_impl(resolve_req, db)
    dest = await db.scalar(select(Destination).where(Destination.id == resolved_schema.id))
    if dest is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Impossible de résoudre la destination pour la ville {city_name}.",
        )
    return dest


async def ensure_trip_stages(db: AsyncSession, trip: Trip) -> list[TripStage]:
    """
    Charge les étapes ordonnées d'un voyage.
    Si un séjour mono-ville a été créé directement sans ligne dans trip_stages,
    crée automatiquement son étape unique afin qu'il fonctionne à l'identique.
    """
    stmt = (
        select(TripStage)
        .where(TripStage.trip_id == trip.id)
        .order_by(TripStage.order_index.asc(), TripStage.arrival_date.asc())
    )
    stages = list((await db.scalars(stmt)).all())
    if stages:
        return stages

    dest = await db.scalar(select(Destination).where(Destination.id == trip.destination_id))
    tz_name = dest.timezone if dest else "UTC"
    arr_utc = ensure_utc(trip.arrival_at) if trip.arrival_at else datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc)
    dep_utc = ensure_utc(trip.departure_at) if trip.departure_at else (arr_utc + timedelta(days=3))
    if dep_utc <= arr_utc:
        dep_utc = arr_utc + timedelta(days=1)

    arr_local_date = to_destination_local(arr_utc, tz_name).date()
    dep_local_date = to_destination_local(dep_utc, tz_name).date()
    nights = max(1, (dep_local_date - arr_local_date).days)
    dep_local_date = arr_local_date + timedelta(days=nights)

    flight = await db.scalar(select(FlightBooking).where(FlightBooking.trip_id == trip.id))
    is_seed = (
        normalize_geonames_query(dest.city_name) in SEED_CITY_NAMES_LOWER
        if dest is not None
        else True
    )
    unlocked = bool(flight is not None or not is_seed)

    stage = TripStage(
        trip_id=trip.id,
        order_index=1,
        destination_id=trip.destination_id,
        geoname_id=dest.geoname_id if dest else None,
        city_name=dest.city_name if dest else "Ville",
        country_name=dest.country_name if dest else "Monde",
        country_code_iso2=(dest.country_code_iso2 if dest else "XX")[:2],
        arrival_date=arr_local_date,
        nights=nights,
        departure_date=dep_local_date,
        arrival_at=arr_utc,
        departure_at=dep_utc,
        timezone=tz_name,
        arrival_transport_mode=StageArrivalTransportMode.VOL.value,
        departure_transport_mode=StageArrivalTransportMode.VOL.value,
        transport_unlocked=unlocked,
        transport_booking_ref=flight.pnr_reference if flight else None,
        selected_place_ids=list(trip.selected_place_ids or []),
        planned_budget=float(trip.total_budget_planned) if trip.total_budget_planned is not None else None,
    )
    db.add(stage)
    await db.flush()

    # Rattache les éléments enfants existants du séjour mono-ville à cette étape
    for model_cls in (ItineraryItem, BudgetItem, FlightBooking, AccommodationBooking):
        rows = list(
            (
                await db.scalars(
                    select(model_cls).where(
                        model_cls.trip_id == trip.id,
                        model_cls.stage_id.is_(None),
                    )
                )
            ).all()
        )
        for row in rows:
            row.stage_id = stage.id

    await db.flush()
    return [stage]


def sync_trip_header_from_stages(trip: Trip, stages: list[TripStage]) -> None:
    """Maintient Trip.destination_id, Trip.arrival_at et Trip.departure_at synchronisés avec les étapes."""
    if not stages:
        return
    ordered = sorted(stages, key=lambda s: s.order_index)
    first = ordered[0]
    last = ordered[-1]
    trip.destination_id = first.destination_id
    trip.arrival_at = ensure_utc(first.arrival_at)
    trip.departure_at = ensure_utc(last.departure_at)


def get_effective_departure_mode_for_stage(stages: list[TripStage], stage_idx: int) -> str:
    """
    Détermine le mode de transport de départ d'une étape :
    - Si departure_transport_mode est renseigné sur l'étape, l'utilise ;
    - Sinon, s'il y a une étape suivante (stage_idx + 1), utilise le mode d'arrivée de l'étape suivante ;
    - Pour la dernière étape du voyage, utilise le mode d'arrivée de la 1re étape (ou de l'étape courante).
    """
    stage = stages[stage_idx]
    if stage.departure_transport_mode:
        return normalize_stage_transport_mode(stage.departure_transport_mode)
    if stage_idx + 1 < len(stages):
        return normalize_stage_transport_mode(stages[stage_idx + 1].arrival_transport_mode)
    return normalize_stage_transport_mode(stages[0].arrival_transport_mode or stage.arrival_transport_mode)


def compute_stage_window_info(stages: list[TripStage], stage_idx: int) -> dict[str, Any]:
    """
    Calcule la fenêtre de visite effective de l'étape dans son propre fuseau horaire :
    - Avion (VOL) : arrivée + 2 h jusqu'à départ - 3 h (configurables via TRIP_ARRIVAL/DEPARTURE_BUFFER_HOURS)
    - Train / Bus / Bateau / Voiture : tampons réduits configurables.
    """
    stage = stages[stage_idx]
    arr_mode = normalize_stage_transport_mode(stage.arrival_transport_mode)
    dep_mode = get_effective_departure_mode_for_stage(stages, stage_idx)

    arr_buf_h = get_arrival_buffer_hours_for_mode(arr_mode)
    dep_buf_h = get_departure_buffer_hours_for_mode(dep_mode)

    raw_arr_utc = ensure_utc(stage.arrival_at)
    raw_dep_utc = ensure_utc(stage.departure_at)
    eff_start_utc = raw_arr_utc + timedelta(hours=arr_buf_h)
    eff_end_utc = raw_dep_utc - timedelta(hours=dep_buf_h)

    tz_name = stage.timezone or "UTC"
    loc_arr = to_destination_local(raw_arr_utc, tz_name)
    loc_dep = to_destination_local(raw_dep_utc, tz_name)
    loc_eff_start = to_destination_local(eff_start_utc, tz_name)
    loc_eff_end = to_destination_local(eff_end_utc, tz_name)

    return {
        "stage_id": stage.id,
        "order_index": stage.order_index,
        "timezone": tz_name,
        "arrival_transport_mode": arr_mode,
        "departure_transport_mode": dep_mode,
        "arrival_buffer_hours": arr_buf_h,
        "departure_buffer_hours": dep_buf_h,
        "arrival_at_utc": raw_arr_utc,
        "departure_at_utc": raw_dep_utc,
        "effective_start_utc": eff_start_utc,
        "effective_end_utc": eff_end_utc,
        "arrival_local": loc_arr.isoformat(),
        "departure_local": loc_dep.isoformat(),
        "visit_window_start_utc": eff_start_utc,
        "visit_window_end_utc": eff_end_utc,
        "visit_window_start_local": loc_eff_start.isoformat(),
        "visit_window_end_local": loc_eff_end.isoformat(),
    }


def resolve_stage_for_visit(
    stages: list[TripStage],
    *,
    visit_date: date | None = None,
    local_start_time: str | None = None,
    duration_minutes: int | None = None,
    start_at_utc: datetime | None = None,
    place: Place | None = None,
    stage_id: str | None = None,
    explicit_stage_id: str | None = None,
) -> tuple[TripStage, int]:
    """
    Retrouve l'étape correspondant à une visite :
    1. Si stage_id est fourni explicitement, utilise cette étape.
    2. Si un lieu (place) est fourni et que sa destination correspond à une étape couvrant visit_date
       (y compris un jour de transition entre deux étapes !), retourne cette étape.
    3. Retrouve l'étape par la date (visit_date) et, à la limite de deux étapes le jour de transition,
       départage par le lieu ou l'horaire UTC (avant le départ de l'étape i vs après l'arrivée de l'étape i+1).
    """
    if not stages:
        raise ValueError("Aucune étape disponible sur ce voyage.")

    ordered = sorted(stages, key=lambda s: s.order_index)
    if len(ordered) == 1:
        return ordered[0], 0

    chosen_stage_id = stage_id or explicit_stage_id
    if chosen_stage_id:
        for idx, st in enumerate(ordered):
            if st.id == chosen_stage_id:
                return st, idx

    # Si le lieu appartient à une ville précise du parcours
    if place is not None:
        matching_dest_stages = [
            (st, idx) for idx, st in enumerate(ordered) if st.destination_id == place.destination_id
        ]
        if visit_date is not None:
            for st, idx in matching_dest_stages:
                if st.arrival_date <= visit_date <= st.departure_date:
                    return st, idx
        if len(matching_dest_stages) == 1 and visit_date is None:
            return matching_dest_stages[0]

    # Recherche par date de visite (utilisé notamment par le chat, la voix et le calendrier)
    if visit_date is not None:
        covering = [
            (st, idx)
            for idx, st in enumerate(ordered)
            if st.arrival_date <= visit_date <= st.departure_date
        ]
        if len(covering) == 1:
            return covering[0]
        if len(covering) >= 2:
            # Jour de transition (limite entre deux étapes consécutives : départ étape k / arrivée étape k+1)
            prev_st, prev_idx = covering[0]
            next_st, next_idx = covering[1]
            if place is not None:
                if place.destination_id == prev_st.destination_id:
                    return prev_st, prev_idx
                if place.destination_id == next_st.destination_id:
                    return next_st, next_idx
            if start_at_utc is not None:
                utc_dt = ensure_utc(start_at_utc)
                if utc_dt <= ensure_utc(prev_st.departure_at):
                    return prev_st, prev_idx
                return next_st, next_idx
            # Par défaut sur une date seule, privilégie l'étape où l'on passe la nuit ce soir-là (arrival_date == visit_date)
            for st, idx in covering:
                if st.arrival_date <= visit_date < st.departure_date:
                    return st, idx
            return next_st, next_idx

        # Si la date est avant la 1re étape ou après la dernière étape
        if visit_date < ordered[0].arrival_date:
            return ordered[0], 0
        if visit_date > ordered[-1].departure_date:
            return ordered[-1], len(ordered) - 1

    if start_at_utc is not None:
        utc_dt = ensure_utc(start_at_utc)
        for idx, st in enumerate(ordered):
            if ensure_utc(st.arrival_at) <= utc_dt <= ensure_utc(st.departure_at):
                return st, idx
        if utc_dt < ensure_utc(ordered[0].arrival_at):
            return ordered[0], 0
        return ordered[-1], len(ordered) - 1

    if place is not None:
        for idx, st in enumerate(ordered):
            if st.destination_id == place.destination_id:
                return st, idx

    return ordered[0], 0


def build_comparator_links_for_mode(
    mode: str,
    origin_city: str,
    destination_city: str,
    travel_date: date,
    origin_iata: str | None = None,
    destination_iata: str | None = None,
) -> dict[str, str]:
    """
    Construit les liens de comparateurs réels adaptés au type de trajet (vol, train, bus, bateau, voiture).
    Aucun horaire ni compagnie inventés.
    """
    norm_mode = normalize_stage_transport_mode(mode)
    date_iso = travel_date.isoformat()
    o_city_q = quote_plus(origin_city)
    d_city_q = quote_plus(destination_city)

    if norm_mode == StageArrivalTransportMode.VOL.value:
        o_iata = (origin_iata or "CDG").upper()
        d_iata = (destination_iata or "FCO").upper()
        return {
            "google_flights": f"https://www.google.com/travel/flights?hl=fr&q=Flights+from+{o_iata}+to+{d_iata}+on+{date_iso}",
            "skyscanner": f"https://www.skyscanner.fr/transport/vols/{o_iata.lower()}/{d_iata.lower()}/{travel_date.strftime('%y%m%d')}/",
            "kayak": f"https://www.kayak.fr/flights/{o_iata}-{d_iata}/{date_iso}?sort=bestflight_a",
        }

    if norm_mode == StageArrivalTransportMode.TRAIN.value:
        return {
            "trainline": f"https://www.thetrainline.com/fr/horaires-train/{o_city_q}-a-{d_city_q}?outwardDate={date_iso}",
            "sncf_connect": f"https://www.sncf-connect.com/train/trajet/{o_city_q}/{d_city_q}?date={date_iso}",
            "omio": f"https://fr.omio.com/trains/{o_city_q}/{d_city_q}?departure_date={date_iso}",
            "rome2rio": f"https://www.rome2rio.com/fr/map/{o_city_q}/{d_city_q}",
        }

    if norm_mode == StageArrivalTransportMode.BUS.value:
        return {
            "omio": f"https://fr.omio.com/bus/{o_city_q}/{d_city_q}?departure_date={date_iso}",
            "flixbus": f"https://shop.flixbus.fr/search?departureCityName={o_city_q}&arrivalCityName={d_city_q}&rideDate={travel_date.strftime('%d.%m.%Y')}",
            "busbud": f"https://www.busbud.com/fr/bus-schedules-results/{o_city_q}/{d_city_q}?outbound_date={date_iso}",
            "rome2rio": f"https://www.rome2rio.com/fr/map/{o_city_q}/{d_city_q}",
        }

    if norm_mode == StageArrivalTransportMode.BATEAU.value:
        return {
            "direct_ferries": f"https://www.directferries.fr/?origin={o_city_q}&destination={d_city_q}&date={date_iso}",
            "ferryhopper": f"https://www.ferryhopper.com/fr/?origin={o_city_q}&destination={d_city_q}&date={date_iso}",
            "rome2rio": f"https://www.rome2rio.com/fr/map/{o_city_q}/{d_city_q}",
        }

    # VOITURE
    return {
        "openstreetmap_directions": f"https://www.openstreetmap.org/directions?from={o_city_q}&to={d_city_q}",
        "mappy": f"https://fr.mappy.com/itineraire#/voiture/{o_city_q}/{d_city_q}",
        "rome2rio": f"https://www.rome2rio.com/fr/map/{o_city_q}/{d_city_q}",
    }


async def build_stage_transport_details(
    db: AsyncSession,
    trip: Trip,
    stages: list[TripStage],
    stage_idx: int,
    *,
    default_origin_city: str = "Paris",
    default_origin_iata: str = "CDG",
) -> dict[str, Any]:
    """
    Construit les informations de trajet d'arrivée pour l'étape `stage_idx` :
    - Pour les vols (VOL) : offres d'exemple basées sur la distance réelle OurAirports,
      avec bandeau "Offres d'exemple, prix indicatifs" et aucun nom de compagnie ou numéro
      de vol inventé hors catalogue.
    - Pour train, bus, bateau (et voiture) : liens de comparateurs réels, sans aucun horaire
      ni nom de compagnie inventés (flight_offers=[], company=None, schedule=None).
    """
    stage = stages[stage_idx]
    dest = await db.scalar(select(Destination).where(Destination.id == stage.destination_id))
    dest_city = stage.city_name or (dest.city_name if dest else "Destination")
    dest_lat = float(dest.latitude) if dest else 41.9028
    dest_lng = float(dest.longitude) if dest else 12.4964
    dest_airport = find_nearest_airport(
        dest_lat,
        dest_lng,
        city_name=dest_city,
        country_code=stage.country_code_iso2,
    )
    dest_iata = str(dest_airport.get("iata_code") or (dest.iata_code if dest else "FCO")).upper()

    if stage_idx > 0:
        prev_stage = stages[stage_idx - 1]
        prev_dest = await db.scalar(
            select(Destination).where(Destination.id == prev_stage.destination_id)
        )
        orig_city = prev_stage.city_name or (prev_dest.city_name if prev_dest else default_origin_city)
        orig_lat = float(prev_dest.latitude) if prev_dest else 48.8566
        orig_lng = float(prev_dest.longitude) if prev_dest else 2.3522
        orig_airport = find_nearest_airport(
            orig_lat,
            orig_lng,
            city_name=orig_city,
            country_code=prev_stage.country_code_iso2,
        )
        orig_iata = str(
            orig_airport.get("iata_code") or (prev_dest.iata_code if prev_dest else default_origin_iata)
        ).upper()
    else:
        orig_city = default_origin_city
        orig_iata = (getattr(trip, "origin_iata", None) or default_origin_iata or "CDG").upper()
        if are_airport_codes_equivalent(orig_iata, dest_iata):
            orig_city = "Londres"
            orig_iata = "LHR"
        orig_ap = resolve_airport_record(orig_iata)
        orig_lat = float(orig_ap.latitude) if orig_ap else 48.8566
        orig_lng = float(orig_ap.longitude) if orig_ap else 2.3522

    dist_km = round(haversine_distance_km(orig_lat, orig_lng, dest_lat, dest_lng), 1)
    mode = normalize_stage_transport_mode(stage.arrival_transport_mode)
    comparators = build_comparator_links_for_mode(
        mode=mode,
        origin_city=orig_city,
        destination_city=dest_city,
        travel_date=stage.arrival_date,
        origin_iata=orig_iata,
        destination_iata=dest_iata,
    )
    comparator_links_items = [
        {
            "provider": k,
            "url": v,
            "has_invented_schedule": False,
            "has_invented_company": False,
        }
        for k, v in comparators.items()
    ]

    if mode == StageArrivalTransportMode.VOL.value:
        registry = get_provider_registry()
        return_date = stage.departure_date if stage.departure_date > stage.arrival_date else (stage.arrival_date + timedelta(days=1))
        raw_offers = await registry.flights.search_flights(
            origin_iata=orig_iata,
            destination_iata=dest_iata,
            departure_date=stage.arrival_date,
            return_date=return_date,
            travel_style=trip.travel_style or "STANDARD",
        )
        formatted_offers: list[dict[str, Any]] = []
        for offer in raw_offers:
            price_dec = Decimal(str(offer.get("price_amount", offer.get("price_eur", "120.00")))).quantize(
                Decimal("0.01")
            )
            formatted_offers.append(
                {
                    "offer_id": offer["offer_id"],
                    "origin_iata": orig_iata,
                    "destination_iata": dest_iata,
                    "origin_city": orig_city,
                    "destination_city": dest_city,
                    "airline_code": str(offer.get("airline_code", "")),
                    "airline_name": str(offer.get("airline_name", "Offre d'exemple")),
                    "flight_number_outbound": str(offer.get("flight_number_outbound", "")),
                    "flight_number_inbound": str(offer.get("flight_number_inbound", "")),
                    "departure_outbound_at": offer["departure_outbound_at"].isoformat()
                    if isinstance(offer.get("departure_outbound_at"), datetime)
                    else str(offer.get("departure_outbound_at")),
                    "arrival_outbound_at": offer["arrival_outbound_at"].isoformat()
                    if isinstance(offer.get("arrival_outbound_at"), datetime)
                    else str(offer.get("arrival_outbound_at")),
                    "price_amount": str(price_dec),
                    "currency": str(offer.get("currency", "EUR")),
                    "distance_km": float(offer.get("distance_km") or dist_km),
                    "distance_source": "OurAirports",
                    "is_example_offer": True,
                    "offer_badge": "Offre d'exemple",
                    "price_label": "Prix indicatif",
                    "banner_text": "Offres d'exemple, prix indicatifs",
                    "example_banner": "Offres d'exemple, prix indicatifs",
                    "has_invented_airline": False,
                    "has_invented_flight_number": False,
                    "has_invented_schedule": False,
                    "comparator_urls": offer.get("comparator_urls") or comparators,
                }
            )
        first_offer = formatted_offers[0] if formatted_offers else {
            "origin_iata": orig_iata,
            "destination_iata": dest_iata,
            "distance_km": dist_km,
            "distance_source": "OurAirports",
            "is_example_offer": True,
            "example_banner": "Offres d'exemple, prix indicatifs",
            "has_invented_airline": False,
            "has_invented_flight_number": False,
            "has_invented_schedule": False,
        }
        return {
            "stage_id": stage.id,
            "order_index": stage.order_index,
            "transport_mode": mode,
            "arrival_transport_mode": mode,
            "origin_city": orig_city,
            "destination_city": dest_city,
            "origin_iata": orig_iata,
            "destination_iata": dest_iata,
            "travel_date": stage.arrival_date.isoformat(),
            "distance_km": dist_km,
            "distance_source": "OurAirports",
            "is_example_offer": True,
            "comparator_only": False,
            "banner_text": "Offres d'exemple, prix indicatifs",
            "example_banner": "Offres d'exemple, prix indicatifs",
            "offer_badge": "Offre d'exemple",
            "company": None,
            "schedule": None,
            "flight_example_offer": first_offer,
            "flight_offers": formatted_offers,
            "comparator_urls": comparators,
            "comparator_links": comparator_links_items,
            "transport_unlocked": bool(stage.transport_unlocked),
            "transport_booking_ref": stage.transport_booking_ref,
        }

    # Pour TRAIN, BUS, BATEAU, VOITURE : lien de comparateur uniquement, aucun horaire ni compagnie inventés
    return {
        "stage_id": stage.id,
        "order_index": stage.order_index,
        "transport_mode": mode,
        "arrival_transport_mode": mode,
        "origin_city": orig_city,
        "destination_city": dest_city,
        "origin_iata": None,
        "destination_iata": None,
        "travel_date": stage.arrival_date.isoformat(),
        "distance_km": dist_km,
        "distance_source": "OurAirports",
        "is_example_offer": False,
        "comparator_only": True,
        "banner_text": "Comparateurs de billets externes — aucun horaire ni compagnie simulés.",
        "offer_badge": None,
        "company": None,
        "airline_name": None,
        "flight_number": None,
        "schedule": None,
        "departure_time": None,
        "arrival_time": None,
        "flight_example_offer": None,
        "flight_offers": [],
        "comparator_urls": comparators,
        "comparator_links": comparator_links_items,
        "transport_unlocked": bool(stage.transport_unlocked),
        "transport_booking_ref": stage.transport_booking_ref,
    }

