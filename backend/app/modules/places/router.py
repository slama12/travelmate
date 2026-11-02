from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.redis import cache_client
from app.core.seed import SEED_DESTINATIONS
from app.core.database import AsyncSession, get_db
from app.core.providers import CityNotSimulatedError, get_provider_registry
from app.core.rbac import READ_ROLES, WRITE_ROLES, require_trip_access
from app.models.entities import Destination, FlightBooking, Place, Trip, User, WishlistItem
from app.modules.auth.router import get_current_user
from app.modules.places.schemas import (
    CityPlacesResultResponse,
    PlaceResponse,
    TripGalleryResponse,
    TripPlaceSelectionRequest,
    WishlistToggleRequest,
    WishlistToggleResponse,
)
from app.modules.trips.stages_service import ensure_trip_stages

from app.modules.places.world_place_photos_service import (
    format_photo_credit,
    get_world_place_photo_service,
    world_place_photo_service,
)
from app.modules.places.world_places_service import (
    DEFAULT_SEARCH_RADIUS_KM,
    EXPANDED_SEARCH_RADIUS_KM,
    FEW_PLACES_THRESHOLD,
    MAX_SELECTED_PLACES,
    WorldPlacesFetchResult,
    get_world_places_service,
    normalize_place_text,
    world_places_service,
)

router = APIRouter(prefix="/places", tags=["Places & Gallery"])

SEED_CITIES_LOWER = {"tokyo", "rome", "new york", "marrakech", "paris"}


def _serialize_place(
    place: Place,
    city_name: str,
    wishlisted_ids: set[str],
    selected_ids: set[str],
) -> PlaceResponse:
    op_hours = place.opening_hours or {}
    hours_status = place.hours_status or op_hours.get("status")
    price_label = place.price_label
    if not price_label:
        if place.source_provider and place.source_provider != "simulated":
            price_label = "non renseigné"
        else:
            cost_val = float(place.estimated_cost or 0.0)
            price_label = "Gratuit" if cost_val <= 0 else f"{cost_val:.0f} €"

    photos_list = place.hero_photos or []
    photo_status = "Photo disponible" if photos_list else "Photo bientôt disponible"
    credit_text = format_photo_credit(place.photo_author, place.photo_license)
    photo_checked = bool(
        place.photo_checked_at is not None
        or (place.source_provider or "simulated") == "simulated"
        or (photos_list and credit_text)
    )

    return PlaceResponse(
        id=place.id,
        destination_id=place.destination_id,
        city_name=city_name,
        name=place.name,
        description=place.description,
        category=place.category,
        is_outdoor=place.is_outdoor,
        latitude=place.latitude,
        longitude=place.longitude,
        recommended_duration_min=place.recommended_duration_min,
        estimated_cost=Decimal(str(place.estimated_cost)).quantize(Decimal("0.01")),
        price_tier=place.price_tier,
        avg_rating=place.avg_rating,
        opening_hours=op_hours,
        hero_photos=photos_list,
        photo_status=photo_status,
        source_provider=place.source_provider or "simulated",
        external_place_id=place.external_place_id,
        address=place.address,
        website_url=place.website_url,
        price_label=price_label,
        hours_status=hours_status,
        source_url=place.source_url,
        source_attribution=place.source_attribution,
        notoriety_score=int(place.notoriety_score or 0),
        photo_file_title=place.photo_file_title,
        photo_author=place.photo_author,
        photo_license=place.photo_license,
        photo_commons_url=place.photo_commons_url,
        photo_source=place.photo_source,
        photo_credit_text=credit_text,
        photo_checked=photo_checked,
        is_wishlisted=place.id in wishlisted_ids,
        is_selected_for_trip=place.id in selected_ids,
    )


async def ensure_destination_world_places(
    db: AsyncSession,
    dest: Destination,
    radius_km: int = DEFAULT_SEARCH_RADIUS_KM,
) -> tuple[list[Place], bool, WorldPlacesFetchResult]:
    """
    Garantit le chargement et la mise en cache (table Place + Redis) des lieux d'une ville
    hors démonstration via Wikivoyage / Wikipédia+Wikidata / Overpass.
    - Un seul appel réseau par ville/rayon tant que le cache est valide.
    - En cas de panne, replie sur le cache base/Redis si présent, sinon renvoie
      outage_message="Les lieux de cette ville sont momentanément indisponibles".
    """
    norm_city = normalize_place_text(dest.city_name)
    cache_key = f"places:world:v2:{norm_city}:r{radius_km}"
    base_cache_key = f"places:world:v2:{norm_city}:r{DEFAULT_SEARCH_RADIUS_KM}"

    stmt = (
        select(Place)
        .where(Place.destination_id == dest.id)
        .order_by(Place.notoriety_score.desc(), Place.id.asc())
    )
    existing_places = list((await db.scalars(stmt)).all())

    cached_marker = await cache_client.get_json(cache_key)
    cached_in_redis = bool(cached_marker and cached_marker.get("cached"))

    # Si le cache Redis est valide pour ce rayon (ou si la base a déjà >= 5 lieux et rayon standard),
    # aucun appel réseau n'est déclenché.
    if (cached_in_redis and existing_places) or (
        cached_in_redis and cached_marker and cached_marker.get("place_count") == 0
    ):
        few_msg = (
            f"Peu de lieux disponibles à {dest.city_name} pour l'instant"
            if len(existing_places) < FEW_PLACES_THRESHOLD
            else None
        )
        can_expand = len(existing_places) < FEW_PLACES_THRESHOLD and radius_km < EXPANDED_SEARCH_RADIUS_KM
        return (
            existing_places[:MAX_SELECTED_PLACES],
            True,
            WorldPlacesFetchResult(
                city_name=dest.city_name,
                radius_km=radius_km,
                places=[],
                few_places_message=few_msg,
                can_expand_radius=can_expand,
                suggested_radius_km=EXPANDED_SEARCH_RADIUS_KM if can_expand else None,
                outage_message=None,
                cached_in_redis=True,
                cached_in_db=True,
            ),
        )

    if existing_places and radius_km <= DEFAULT_SEARCH_RADIUS_KM:
        few_msg = (
            f"Peu de lieux disponibles à {dest.city_name} pour l'instant"
            if len(existing_places) < FEW_PLACES_THRESHOLD
            else None
        )
        can_expand = len(existing_places) < FEW_PLACES_THRESHOLD and radius_km < EXPANDED_SEARCH_RADIUS_KM
        await cache_client.set_json(
            cache_key,
            {
                "cached": True,
                "city_name": dest.city_name,
                "radius_km": radius_km,
                "place_count": len(existing_places),
                "place_ids": [p.id for p in existing_places],
            },
            ttl_seconds=86400,
        )
        return (
            existing_places[:MAX_SELECTED_PLACES],
            True,
            WorldPlacesFetchResult(
                city_name=dest.city_name,
                radius_km=radius_km,
                places=[],
                few_places_message=few_msg,
                can_expand_radius=can_expand,
                suggested_radius_km=EXPANDED_SEARCH_RADIUS_KM if can_expand else None,
                outage_message=None,
                cached_in_redis=True,
                cached_in_db=True,
            ),
        )

    # Interrogation de WorldPlacesService (Wikivoyage + Wikipédia/Wikidata + Overpass optionnel)
    svc = get_world_places_service()
    fetch_result = await svc.fetch_city_places(
        city_name=dest.city_name,
        city_lat=float(dest.latitude or 0.0),
        city_lon=float(dest.longitude or 0.0),
        radius_km=radius_km,
    )

    if fetch_result.outage_message:
        # Règle 8 : Panne -> utilise le cache si présent, sinon message d'indisponibilité, aucune donnée inventée
        if existing_places:
            few_msg = (
                f"Peu de lieux disponibles à {dest.city_name} pour l'instant"
                if len(existing_places) < FEW_PLACES_THRESHOLD
                else None
            )
            can_expand = len(existing_places) < FEW_PLACES_THRESHOLD and radius_km < EXPANDED_SEARCH_RADIUS_KM
            return (
                existing_places[:MAX_SELECTED_PLACES],
                cached_in_redis,
                WorldPlacesFetchResult(
                    city_name=dest.city_name,
                    radius_km=radius_km,
                    places=[],
                    few_places_message=few_msg,
                    can_expand_radius=can_expand,
                    suggested_radius_km=EXPANDED_SEARCH_RADIUS_KM if can_expand else None,
                    outage_message=None,
                    cached_in_redis=cached_in_redis,
                    cached_in_db=True,
                ),
            )
        return ([], False, fetch_result)

    by_ext_key: dict[tuple[str, str], Place] = {
        (p.source_provider or "", p.external_place_id or ""): p
        for p in existing_places
        if p.external_place_id
    }
    by_norm_name: dict[str, Place] = {
        normalize_place_text(p.name): p for p in existing_places if p.name
    }

    for item in fetch_result.places:
        ext_key = (item.source_provider, item.external_place_id)
        norm_item_name = normalize_place_text(item.name)
        existing_row = by_ext_key.get(ext_key) or by_norm_name.get(norm_item_name)
        if existing_row:
            existing_row.notoriety_score = max(int(existing_row.notoriety_score or 0), int(item.notoriety_score))
            if not existing_row.address and item.address:
                existing_row.address = item.address
            if not existing_row.website_url and item.website_url:
                existing_row.website_url = item.website_url
            if not existing_row.source_url and item.source_url:
                existing_row.source_url = item.source_url
            if not existing_row.source_attribution and item.source_attribution:
                existing_row.source_attribution = item.source_attribution
        else:
            raw_tier = str(item.price_tier or "STANDARD").upper()
            normalized_tier = (
                "ECONOMIC"
                if raw_tier in ("ECONOMIC", "ECO", "BUDGET", "FREE")
                else ("LUXURY" if raw_tier == "LUXURY" else "STANDARD")
            )
            new_place = Place(
                destination_id=dest.id,
                name=(item.name or "")[:200],
                description=item.description,
                category=item.category,
                is_outdoor=item.is_outdoor,
                latitude=item.latitude,
                longitude=item.longitude,
                recommended_duration_min=item.recommended_duration_min,
                estimated_cost=Decimal(str(item.estimated_cost)).quantize(Decimal("0.01")),
                price_tier=normalized_tier,
                avg_rating=4.6,
                opening_hours=item.opening_hours,
                hero_photos=[],
                source_provider=(item.source_provider or "")[:50],
                external_place_id=(item.external_place_id[:120] if item.external_place_id else None),
                address=(item.address[:255] if item.address else None),
                website_url=(item.website_url[:500] if item.website_url else None),
                price_label=(item.price_label[:120] if item.price_label else None),
                hours_status=(item.hours_status[:60] if item.hours_status else None),
                source_url=(item.source_url[:500] if item.source_url else None),
                source_attribution=(item.source_attribution[:255] if item.source_attribution else None),
                notoriety_score=int(item.notoriety_score),
            )
            db.add(new_place)
            existing_places.append(new_place)
            by_ext_key[ext_key] = new_place
            by_norm_name[norm_item_name] = new_place

    await db.commit()
    stmt_refreshed = (
        select(Place)
        .where(Place.destination_id == dest.id)
        .order_by(Place.notoriety_score.desc(), Place.id.asc())
    )
    final_places = list((await db.scalars(stmt_refreshed)).all())[:MAX_SELECTED_PLACES]

    cache_payload = {
        "cached": True,
        "city_name": dest.city_name,
        "radius_km": radius_km,
        "place_count": len(final_places),
        "place_ids": [p.id for p in final_places],
    }
    await cache_client.set_json(cache_key, cache_payload, ttl_seconds=86400)
    if radius_km == DEFAULT_SEARCH_RADIUS_KM:
        await cache_client.set_json(base_cache_key, cache_payload, ttl_seconds=86400)

    few_msg = (
        f"Peu de lieux disponibles à {dest.city_name} pour l'instant"
        if len(final_places) < FEW_PLACES_THRESHOLD
        else None
    )
    can_expand = len(final_places) < FEW_PLACES_THRESHOLD and radius_km < EXPANDED_SEARCH_RADIUS_KM
    fetch_result.few_places_message = few_msg
    fetch_result.can_expand_radius = can_expand
    fetch_result.suggested_radius_km = EXPANDED_SEARCH_RADIUS_KM if can_expand else None

    return (final_places, True, fetch_result)


async def _get_or_fetch_city_places(
    city_name: str,
    category: str | None,
    db: AsyncSession,
    radius_km: int = DEFAULT_SEARCH_RADIUS_KM,
) -> tuple[Destination, list[Place], bool, str, WorldPlacesFetchResult | None]:
    """
    Récupère les lieux d'une ville :
    1. Pour les 5 villes du seed : conserve leurs 14 lieux de démonstration.
    2. Pour une ville du monde dotée de coordonnées réelles ou geoname_id (et lorsque registry.places est en mode standard) :
       utilise WorldPlacesService (Wikivoyage + Wikipédia/Wikidata + Overpass optionnel) avec cache DB + Redis.
    3. Pour les appels de test legacy sans coordonnées / geoname_id ou avec provider 'real' mocké :
       conserve le comportement registry.places.search_city_highlights.
    """
    registry = get_provider_registry()
    provider_mode = registry.places.mode
    norm_city = city_name.strip()
    cache_key = f"places:city:{norm_city.lower()}:{provider_mode}"

    cached_marker = await cache_client.get_json(cache_key)
    cached_in_redis = bool(cached_marker and cached_marker.get("cached"))

    dest = await db.scalar(
        select(Destination).where(func.lower(Destination.city_name) == norm_city.lower())
    )

    # Si c'est une vraie ville hors seed (avec geoname_id ou coordonnées réelles non nulles) et qu'aucun mock provider 'real' n'est injecté
    is_real_world_destination = bool(
        dest
        and dest.city_name.strip().lower() not in SEED_CITIES_LOWER
        and provider_mode == "simulated"
        and dest.geoname_id is not None
    )
    if is_real_world_destination and dest is not None:
        places_list, world_cached, world_res = await ensure_destination_world_places(
            db=db,
            dest=dest,
            radius_km=radius_km,
        )
        if category:
            places_list = [p for p in places_list if p.category.upper() == category.upper()]
        return dest, places_list, world_cached, "wikivoyage_wikipedia", world_res

    existing_places: list[Place] = []
    if dest:
        stmt = select(Place).where(Place.destination_id == dest.id)
        existing_places = list((await db.scalars(stmt)).all())
        seed_dest = next(
            (d for d in SEED_DESTINATIONS if d["city_name"].lower() == dest.city_name.lower()),
            None,
        )
        if seed_dest and existing_places:
            order_map = {
                p_item["name"]: idx for idx, p_item in enumerate(seed_dest.get("places", []))
            }
            existing_places.sort(key=lambda pl: (order_map.get(pl.name, 999), pl.name))

    if not existing_places:
        # Interrogation du provider (SimulatedPlacesProvider ou RealPlacesProvider)
        fetched_items = await registry.places.search_city_highlights(
            city_name=norm_city,
            category=None,
        )
        if not dest:
            first_lat = float(fetched_items[0]["latitude"]) if fetched_items else 48.8566
            first_lng = float(fetched_items[0]["longitude"]) if fetched_items else 2.3522
            dest = Destination(
                city_name=norm_city,
                country_name="Monde",
                country_code_iso2="XX",
                iata_code=norm_city[:3].upper(),
                timezone="UTC",
                latitude=first_lat,
                longitude=first_lng,
                hero_image_url=(
                    fetched_items[0]["hero_photos"][0]
                    if fetched_items and fetched_items[0].get("hero_photos")
                    else "https://images.unsplash.com/photo-1488646953014-85cb44e25828?auto=format&fit=crop&w=1400&q=80"
                ),
                description=f"Destination {norm_city} chargée à la demande ({provider_mode}).",
                practical_info={},
                useful_phrases=[],
            )
            db.add(dest)
            await db.flush()

        for item in fetched_items:
            new_place = Place(
                destination_id=dest.id,
                name=item["name"],
                description=item.get("description", ""),
                category=item.get("category", "CULTURE"),
                is_outdoor=bool(item.get("is_outdoor", False)),
                latitude=float(item.get("latitude", dest.latitude)),
                longitude=float(item.get("longitude", dest.longitude)),
                recommended_duration_min=int(item.get("recommended_duration_min", 120)),
                estimated_cost=Decimal(str(item.get("estimated_cost", 0.0))).quantize(Decimal("0.01")),
                price_tier=item.get("price_tier", "STANDARD"),
                avg_rating=float(item.get("avg_rating", 4.6)),
                opening_hours=item.get("opening_hours", {"daily": "09:00-18:00"}),
                hero_photos=item.get("hero_photos", []),
                source_provider=item.get("source_provider", provider_mode),
                external_place_id=item.get("external_place_id"),
                photo_file_title=item.get("photo_file_title"),
                photo_author=item.get("photo_author"),
                photo_license=item.get("photo_license"),
                photo_commons_url=item.get("photo_commons_url"),
                photo_source=item.get("photo_source"),
            )
            db.add(new_place)
            existing_places.append(new_place)

        await db.commit()
        for p in existing_places:
            await db.refresh(p)

        await cache_client.set_json(
            cache_key,
            {
                "cached": True,
                "city_name": dest.city_name,
                "provider_mode": provider_mode,
                "place_ids": [p.id for p in existing_places],
            },
            ttl_seconds=3600,
        )
        cached_in_redis = True
    elif not cached_in_redis:
        await cache_client.set_json(
            cache_key,
            {
                "cached": True,
                "city_name": dest.city_name,
                "provider_mode": provider_mode,
                "place_ids": [p.id for p in existing_places],
            },
            ttl_seconds=3600,
        )

    if category:
        existing_places = [
            p for p in existing_places if p.category.upper() == category.upper()
        ]

    return dest, existing_places, cached_in_redis, provider_mode, None


@router.get("/city/{city_name}", response_model=CityPlacesResultResponse)
async def list_places_by_city(
    city_name: str,
    category: str | None = Query(default=None),
    radius_km: int = Query(default=DEFAULT_SEARCH_RADIUS_KM, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CityPlacesResultResponse:
    wish_rows = list(
        (
            await db.scalars(
                select(WishlistItem).where(WishlistItem.user_id == current_user.id)
            )
        ).all()
    )
    wishlisted_ids = {w.place_id for w in wish_rows}

    try:
        dest, places, cached_in_redis, provider_mode, world_res = await _get_or_fetch_city_places(
            city_name=city_name,
            category=category,
            db=db,
            radius_km=radius_km,
        )
    except CityNotSimulatedError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "CITY_NOT_AVAILABLE_IN_SIMULATION",
                "city_name": city_name,
                "provider_mode": "simulated",
                "message": str(exc),
            },
        ) from exc

    msg = (
        world_res.outage_message
        if (world_res and world_res.outage_message)
        else (
            world_res.few_places_message
            if (world_res and world_res.few_places_message)
            else f"{len(places)} lieu(x) disponible(s) pour {dest.city_name}."
        )
    )

    return CityPlacesResultResponse(
        city_name=dest.city_name,
        provider_mode=provider_mode,
        cached_in_redis=cached_in_redis,
        available_in_current_mode=True,
        message=msg,
        few_places_message=world_res.few_places_message if world_res else None,
        can_expand_radius=world_res.can_expand_radius if world_res else False,
        suggested_radius_km=world_res.suggested_radius_km if world_res else None,
        radius_km=radius_km,
        outage_message=world_res.outage_message if world_res else None,
        places=[_serialize_place(p, dest.city_name, wishlisted_ids, set()) for p in places],
    )


@router.get("/trip/{trip_id}/gallery", response_model=TripGalleryResponse)
@router.get("/trip/{trip_id}/stages/{stage_id}/gallery", response_model=TripGalleryResponse)
@router.get(
    "/trip/{trip_id}/steps/{stage_id}/gallery",
    response_model=TripGalleryResponse,
    include_in_schema=False,
)
async def get_trip_places_gallery(
    trip_id: str,
    stage_id: str | None = None,
    category: str | None = Query(default=None),
    radius_km: int = Query(default=DEFAULT_SEARCH_RADIUS_KM, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TripGalleryResponse:
    """
    Galerie des lieux d'une ville / d'une étape :
    - Le déblocage de la galerie se fait par étape, après validation du trajet d'arrivée de cette étape.
    - Pour un séjour mono-ville : garde le comportement existant (14 lieux pour les 5 villes de démo
      débloqués après le vol ; villes du monde depuis Wikivoyage/Wikipédia/Wikidata).
    """
    trip, _trip_dest, _role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=READ_ROLES
    )
    stages = await ensure_trip_stages(db, trip)
    is_multi_stage = len(stages) > 1 or stage_id is not None

    if stage_id is not None:
        target_stage = next((st for st in stages if st.id == stage_id), None)
        if target_stage is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Étape introuvable sur ce voyage.",
            )
    else:
        target_stage = stages[0] if stages else None

    target_dest_id = target_stage.destination_id if target_stage else trip.destination_id
    dest = await db.scalar(select(Destination).where(Destination.id == target_dest_id))
    city_name = (
        target_stage.city_name
        if target_stage and target_stage.city_name
        else (dest.city_name if dest else "Destination")
    )
    registry = get_provider_registry()

    wish_rows = list(
        (
            await db.scalars(
                select(WishlistItem).where(WishlistItem.user_id == current_user.id)
            )
        ).all()
    )
    wishlisted_ids = {w.place_id for w in wish_rows}
    stage_selected_list = (
        list(target_stage.selected_place_ids or [])
        if (target_stage and target_stage.selected_place_ids)
        else list(trip.selected_place_ids or [])
    )
    selected_ids = set(stage_selected_list)

    bookings = list(
        (
            await db.scalars(
                select(FlightBooking).where(FlightBooking.trip_id == trip.id)
            )
        ).all()
    )
    stage_bookings = (
        [b for b in bookings if b.stage_id == target_stage.id]
        if target_stage is not None
        else bookings
    )

    is_seed_city = city_name.strip().lower() in SEED_CITIES_LOWER

    # En mode multi-étapes (ou quand stage_id est ciblé), le déblocage se fait strictement par étape
    if is_multi_stage and target_stage is not None:
        stage_unlocked = bool(target_stage.transport_unlocked or stage_bookings)
        if not stage_unlocked:
            mode_label = (target_stage.arrival_transport_mode or "VOL").lower()
            return TripGalleryResponse(
                trip_id=trip.id,
                stage_id=target_stage.id,
                order_index=target_stage.order_index,
                city_name=city_name,
                unlocked=False,
                unlock_message=(
                    f"Galerie de l'étape {target_stage.order_index} ({city_name}) verrouillée : "
                    f"validez d'abord le trajet d'arrivée ({mode_label}) de cette étape pour débloquer ses lieux."
                ),
                provider_mode=registry.places.mode if is_seed_city else "wikivoyage_wikipedia",
                cached_in_redis=False,
                selected_place_ids=[],
                places=[],
            )

    if not is_seed_city and dest is not None:
        places, cached_in_redis, world_res = await ensure_destination_world_places(
            db=db,
            dest=dest,
            radius_km=radius_km,
        )
        if category:
            places = [p for p in places if p.category.upper() == category.upper()]

        if world_res.outage_message and not places:
            return TripGalleryResponse(
                trip_id=trip.id,
                stage_id=target_stage.id if target_stage else None,
                order_index=target_stage.order_index if target_stage else 1,
                city_name=dest.city_name,
                unlocked=True,
                unlock_message=world_res.outage_message,
                provider_mode="wikivoyage_wikipedia",
                cached_in_redis=False,
                few_places_message=None,
                can_expand_radius=False,
                suggested_radius_km=None,
                radius_km=radius_km,
                outage_message=world_res.outage_message,
                selected_place_ids=stage_selected_list,
                places=[],
            )

        unlock_msg = (
            world_res.few_places_message
            or f"Découvrez les lieux incontournables à visiter à {dest.city_name}."
        )
        return TripGalleryResponse(
            trip_id=trip.id,
            stage_id=target_stage.id if target_stage else None,
            order_index=target_stage.order_index if target_stage else 1,
            city_name=dest.city_name,
            unlocked=True,
            unlock_message=unlock_msg,
            provider_mode="wikivoyage_wikipedia",
            cached_in_redis=cached_in_redis,
            few_places_message=world_res.few_places_message,
            can_expand_radius=world_res.can_expand_radius,
            suggested_radius_km=world_res.suggested_radius_km,
            radius_km=radius_km,
            outage_message=None,
            selected_place_ids=stage_selected_list,
            places=[
                _serialize_place(p, dest.city_name, wishlisted_ids, selected_ids)
                for p in places
            ],
        )

    is_unlocked_seed = bool(
        (target_stage and target_stage.transport_unlocked) or stage_bookings or (not is_multi_stage and bookings)
    )
    if not is_unlocked_seed:
        return TripGalleryResponse(
            trip_id=trip.id,
            stage_id=target_stage.id if target_stage else None,
            order_index=target_stage.order_index if target_stage else 1,
            city_name=city_name,
            unlocked=False,
            unlock_message=(
                "Galerie verrouillée : réservez d'abord votre billet d'avion pour débloquer "
                f"les meilleurs lieux de {city_name} en grandes photos."
            ),
            provider_mode=registry.places.mode,
            cached_in_redis=False,
            selected_place_ids=[],
            places=[],
        )

    resolved_dest, places, cached_in_redis, provider_mode, _ = await _get_or_fetch_city_places(
        city_name=city_name,
        category=category,
        db=db,
        radius_km=radius_km,
    )

    ref_label = (
        stage_bookings[0].pnr_reference
        if stage_bookings
        else (
            bookings[0].pnr_reference
            if bookings
            else (target_stage.transport_booking_ref if target_stage else "CONFIRMÉ")
        )
    )
    return TripGalleryResponse(
        trip_id=trip.id,
        stage_id=target_stage.id if target_stage else None,
        order_index=target_stage.order_index if target_stage else 1,
        city_name=resolved_dest.city_name,
        unlocked=True,
        unlock_message=(
            f"Galerie débloquée suite à votre trajet d'arrivée ({ref_label}). "
            f"Sélectionnez les lieux que vous souhaitez visiter à {resolved_dest.city_name}."
        ),
        provider_mode=provider_mode,
        cached_in_redis=cached_in_redis,
        selected_place_ids=stage_selected_list,
        places=[
            _serialize_place(p, resolved_dest.city_name, wishlisted_ids, selected_ids)
            for p in places
        ],
    )


@router.post("/trip/{trip_id}/select", response_model=TripGalleryResponse)
async def select_place_for_trip(
    trip_id: str,
    payload: TripPlaceSelectionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TripGalleryResponse:
    trip, _trip_dest, _role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=WRITE_ROLES
    )
    stages = await ensure_trip_stages(db, trip)
    is_multi_stage = len(stages) > 1 or payload.stage_id is not None

    place = await db.scalar(select(Place).where(Place.id == payload.place_id))
    if not place:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lieu introuvable.",
        )

    target_stage = None
    if payload.stage_id:
        target_stage = next((st for st in stages if st.id == payload.stage_id), None)
    if target_stage is None:
        target_stage = next((st for st in stages if st.destination_id == place.destination_id), None)
    if target_stage is None and stages:
        target_stage = stages[0]

    target_dest_id = target_stage.destination_id if target_stage else trip.destination_id
    dest = await db.scalar(select(Destination).where(Destination.id == target_dest_id))
    is_seed_city = bool(dest and dest.city_name.strip().lower() in SEED_CITIES_LOWER)

    bookings = list(
        (
            await db.scalars(
                select(FlightBooking).where(FlightBooking.trip_id == trip.id)
            )
        ).all()
    )
    stage_bookings = (
        [b for b in bookings if b.stage_id == target_stage.id]
        if target_stage is not None
        else bookings
    )
    stage_unlocked = bool(
        (target_stage and target_stage.transport_unlocked)
        or stage_bookings
        or (not is_multi_stage and (bookings or not is_seed_city))
    )
    if not stage_unlocked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous devez valider le trajet d'arrivée de cette étape avant de pouvoir sélectionner des lieux à visiter.",
        )

    current_selected = list(trip.selected_place_ids or [])
    if payload.selected and payload.place_id not in current_selected:
        current_selected.append(payload.place_id)
    elif not payload.selected and payload.place_id in current_selected:
        current_selected.remove(payload.place_id)
    trip.selected_place_ids = current_selected

    if target_stage is not None:
        st_selected = list(target_stage.selected_place_ids or [])
        if payload.selected and payload.place_id not in st_selected:
            st_selected.append(payload.place_id)
        elif not payload.selected and payload.place_id in st_selected:
            st_selected.remove(payload.place_id)
        target_stage.selected_place_ids = st_selected

    await db.commit()
    await db.refresh(trip)

    return await get_trip_places_gallery(
        trip_id=trip.id,
        stage_id=target_stage.id if (is_multi_stage and target_stage) else None,
        category=None,
        radius_km=DEFAULT_SEARCH_RADIUS_KM,
        current_user=current_user,
        db=db,
    )


@router.post("/{place_id}/wishlist", response_model=WishlistToggleResponse)
async def toggle_place_wishlist(
    place_id: str,
    payload: WishlistToggleRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WishlistToggleResponse:
    place = await db.scalar(select(Place).where(Place.id == place_id))
    if not place:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lieu introuvable.",
        )

    existing = await db.scalar(
        select(WishlistItem).where(
            WishlistItem.user_id == current_user.id,
            WishlistItem.place_id == place_id,
        )
    )
    if existing:
        await db.delete(existing)
        wishlisted = False
        notes = None
    else:
        notes = payload.notes if payload else None
        db.add(
            WishlistItem(
                user_id=current_user.id,
                place_id=place_id,
                notes=notes,
            )
        )
        wishlisted = True

    await db.commit()
    all_user_wishes = list(
        (
            await db.scalars(
                select(WishlistItem).where(WishlistItem.user_id == current_user.id)
            )
        ).all()
    )
    return WishlistToggleResponse(
        place_id=place_id,
        wishlisted=wishlisted,
        notes=notes,
        total_wishlist_count=len(all_user_wishes),
    )


@router.get("/wishlist", response_model=list[PlaceResponse])
async def list_user_wishlist(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PlaceResponse]:
    wish_rows = list(
        (
            await db.scalars(
                select(WishlistItem).where(WishlistItem.user_id == current_user.id)
            )
        ).all()
    )
    if not wish_rows:
        return []

    wish_place_ids = [w.place_id for w in wish_rows]
    places = list(
        (await db.scalars(select(Place).where(Place.id.in_(wish_place_ids)))).all()
    )
    dest_map = {
        d.id: d.city_name
        for d in (await db.scalars(select(Destination))).all()
    }
    wish_set = set(wish_place_ids)
    return [
        _serialize_place(p, dest_map.get(p.destination_id, "Monde"), wish_set, set())
        for p in places
    ]


@router.post("/trip/{trip_id}/photos/enrich", response_model=TripGalleryResponse)
async def enrich_trip_places_photos(
    trip_id: str,
    category: str | None = Query(default=None),
    radius_km: int = Query(default=DEFAULT_SEARCH_RADIUS_KM, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TripGalleryResponse:
    """
    Règle 4 (Étape 3) :
    Récupération des photos après l'affichage de la liste (la galerie ne bloque pas),
    en parallèle avec limite de simultanéité (4 requêtes), cache en base et Redis.
    """
    trip = await db.scalar(
        select(Trip).where(Trip.id == trip_id, Trip.owner_id == current_user.id)
    )
    if not trip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voyage introuvable.",
        )

    dest = await db.scalar(select(Destination).where(Destination.id == trip.destination_id))
    if dest and dest.city_name.strip().lower() not in SEED_CITIES_LOWER:
        places = list(
            (
                await db.scalars(
                    select(Place)
                    .where(Place.destination_id == dest.id)
                    .order_by(Place.notoriety_score.desc(), Place.id.asc())
                )
            ).all()
        )
        if not places:
            places, _, _ = await ensure_destination_world_places(
                db=db,
                dest=dest,
                radius_km=radius_km,
            )
        if places:
            photo_svc = get_world_place_photo_service()
            await photo_svc.enrich_places_photos(db, places[:MAX_SELECTED_PLACES])

    return await get_trip_places_gallery(
        trip_id=trip.id,
        category=category,
        radius_km=radius_km,
        current_user=current_user,
        db=db,
    )


@router.post("/city/{city_name}/photos/enrich", response_model=CityPlacesResultResponse)
async def enrich_city_places_photos(
    city_name: str,
    category: str | None = Query(default=None),
    radius_km: int = Query(default=DEFAULT_SEARCH_RADIUS_KM, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CityPlacesResultResponse:
    """
    Enrichit les photos des lieux d'une ville en parallèle (max 4 requêtes) et retourne la liste mise à jour.
    """
    dest = await db.scalar(
        select(Destination).where(func.lower(Destination.city_name) == city_name.strip().lower())
    )
    if dest and dest.city_name.strip().lower() not in SEED_CITIES_LOWER:
        places = list(
            (
                await db.scalars(
                    select(Place)
                    .where(Place.destination_id == dest.id)
                    .order_by(Place.notoriety_score.desc(), Place.id.asc())
                )
            ).all()
        )
        if not places and dest.geoname_id is not None:
            places, _, _ = await ensure_destination_world_places(
                db=db,
                dest=dest,
                radius_km=radius_km,
            )
        if places:
            photo_svc = get_world_place_photo_service()
            await photo_svc.enrich_places_photos(db, places[:MAX_SELECTED_PLACES])

    return await list_places_by_city(
        city_name=city_name,
        category=category,
        radius_km=radius_km,
        current_user=current_user,
        db=db,
    )


@router.post("/photos/backfill")
async def trigger_missing_place_photos_backfill(
    destination_id: str | None = Query(default=None),
    limit: int = Query(default=60, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """
    Règle 4 (Étape 3) :
    Tâche de rattrapage pour les lieux déjà enregistrés en base sans photo.
    """
    _ = current_user
    photo_svc = get_world_place_photo_service()
    return await photo_svc.backfill_missing_place_photos(
        db,
        destination_id=destination_id,
        limit=limit,
    )

