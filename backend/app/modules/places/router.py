from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.redis import cache_client
from app.core.database import AsyncSession, get_db
from app.core.providers import CityNotSimulatedError, get_provider_registry
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

router = APIRouter(prefix="/places", tags=["Places & Gallery"])


def _serialize_place(
    place: Place,
    city_name: str,
    wishlisted_ids: set[str],
    selected_ids: set[str],
) -> PlaceResponse:
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
        opening_hours=place.opening_hours or {},
        hero_photos=place.hero_photos or [],
        source_provider=place.source_provider or "simulated",
        is_wishlisted=place.id in wishlisted_ids,
        is_selected_for_trip=place.id in selected_ids,
    )


async def _get_or_fetch_city_places(
    city_name: str,
    category: str | None,
    db: AsyncSession,
) -> tuple[Destination, list[Place], bool, str]:
    """
    Récupère les lieux d'une ville :
    1. Vérifie d'abord le cache Redis et la table Place.
    2. Si la ville n'a pas encore de lieux en base :
       - En mode 'simulated' : lève CityNotSimulatedError si la ville est absente du seed ("ville non disponible en simulation").
       - En mode 'real' : interroge le provider réel à la demande, persiste dans Place et met en cache dans Redis.
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

    existing_places: list[Place] = []
    if dest:
        stmt = select(Place).where(Place.destination_id == dest.id)
        existing_places = list((await db.scalars(stmt)).all())

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

    return dest, existing_places, cached_in_redis, provider_mode


@router.get("/city/{city_name}", response_model=CityPlacesResultResponse)
async def list_places_by_city(
    city_name: str,
    category: str | None = Query(default=None),
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
        dest, places, cached_in_redis, provider_mode = await _get_or_fetch_city_places(
            city_name=city_name,
            category=category,
            db=db,
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

    return CityPlacesResultResponse(
        city_name=dest.city_name,
        provider_mode=provider_mode,
        cached_in_redis=cached_in_redis,
        available_in_current_mode=True,
        message=f"{len(places)} lieu(x) disponible(s) pour {dest.city_name} (mode: {provider_mode}).",
        places=[_serialize_place(p, dest.city_name, wishlisted_ids, set()) for p in places],
    )


@router.get("/trip/{trip_id}/gallery", response_model=TripGalleryResponse)
async def get_trip_places_gallery(
    trip_id: str,
    category: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TripGalleryResponse:
    """
    Galerie en grandes photos débloquée uniquement après la réservation du billet d'avion.
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
    city_name = dest.city_name if dest else "Destination"
    registry = get_provider_registry()

    seed_cities_lower = {"tokyo", "rome", "new york", "marrakech", "paris"}
    existing_dest_places: list[Place] = []
    if dest:
        existing_dest_places = list(
            (await db.scalars(select(Place).where(Place.destination_id == dest.id))).all()
        )

    is_non_seed_without_places = (
        city_name.strip().lower() not in seed_cities_lower
        and not existing_dest_places
        and registry.places.mode == "simulated"
    )
    if is_non_seed_without_places:
        return TripGalleryResponse(
            trip_id=trip.id,
            city_name=city_name,
            unlocked=True,
            unlock_message="Les lieux de cette ville arrivent bientôt",
            provider_mode=registry.places.mode,
            cached_in_redis=False,
            selected_place_ids=[],
            places=[],
        )

    bookings = list(
        (
            await db.scalars(
                select(FlightBooking).where(FlightBooking.trip_id == trip.id)
            )
        ).all()
    )
    if not bookings:
        return TripGalleryResponse(
            trip_id=trip.id,
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

    wish_rows = list(
        (
            await db.scalars(
                select(WishlistItem).where(WishlistItem.user_id == current_user.id)
            )
        ).all()
    )
    wishlisted_ids = {w.place_id for w in wish_rows}
    selected_ids = set(trip.selected_place_ids or [])

    try:
        resolved_dest, places, cached_in_redis, provider_mode = await _get_or_fetch_city_places(
            city_name=city_name,
            category=category,
            db=db,
        )
    except CityNotSimulatedError:
        return TripGalleryResponse(
            trip_id=trip.id,
            city_name=city_name,
            unlocked=True,
            unlock_message="Les lieux de cette ville arrivent bientôt",
            provider_mode=registry.places.mode,
            cached_in_redis=False,
            selected_place_ids=[],
            places=[],
        )

    return TripGalleryResponse(
        trip_id=trip.id,
        city_name=resolved_dest.city_name,
        unlocked=True,
        unlock_message=(
            f"Galerie débloquée suite à votre réservation de vol (PNR {bookings[0].pnr_reference}). "
            f"Sélectionnez les lieux que vous souhaitez visiter à {resolved_dest.city_name}."
        ),
        provider_mode=provider_mode,
        cached_in_redis=cached_in_redis,
        selected_place_ids=list(trip.selected_place_ids or []),
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
    trip = await db.scalar(
        select(Trip).where(Trip.id == trip_id, Trip.owner_id == current_user.id)
    )
    if not trip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voyage introuvable.",
        )

    bookings = list(
        (
            await db.scalars(
                select(FlightBooking).where(FlightBooking.trip_id == trip.id)
            )
        ).all()
    )
    if not bookings:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous devez réserver votre billet d'avion avant de pouvoir sélectionner des lieux à visiter.",
        )

    place = await db.scalar(select(Place).where(Place.id == payload.place_id))
    if not place:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lieu introuvable.",
        )

    current_selected = list(trip.selected_place_ids or [])
    if payload.selected and payload.place_id not in current_selected:
        current_selected.append(payload.place_id)
    elif not payload.selected and payload.place_id in current_selected:
        current_selected.remove(payload.place_id)

    trip.selected_place_ids = current_selected
    await db.commit()
    await db.refresh(trip)

    return await get_trip_places_gallery(
        trip_id=trip.id,
        category=None,
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
