from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select

from app.core.database import AsyncSession, get_db
from app.core.geo import estimate_walking_minutes, haversine_distance_km, haversine_distance_m
from app.core.providers import get_provider_registry
from app.models.entities import Accommodation, Destination, Place, Trip
from app.models.enums import AccommodationType, PlaceCategory, TripStatus
from app.modules.accommodations.schemas import (
    AccommodationSearchResponse,
    NearbyRestaurantResponse,
)

router = APIRouter(prefix="/accommodations", tags=["Accommodations"])


def _build_source_metadata(
    acc_type: str,
    source_provider: str | None,
    provider_mode: str,
) -> tuple[str, str, str, bool]:
    """
    Détermine la source explicite de chaque hébergement :
    - 'HOTEL' (hôtel officiel ou partenaire)
    - 'AIRBNB' (partenaire / agrégateur ou redirection Airbnb)
    - 'SIMULATED' (donnée de simulation locale)
    """
    sp = (source_provider or "simulated").lower()
    is_sim = provider_mode == "simulated" or sp == "simulated"

    if acc_type.upper() == AccommodationType.AIRBNB.value:
        source_code = "AIRBNB"
        label = (
            "Airbnb (Simulé • Redirection Partenaire)"
            if is_sim
            else "Airbnb (Redirection Partenaire / Agrégateur)"
        )
        return source_code, "airbnb_partner_redirect", label, is_sim

    if sp == "simulated":
        return "SIMULATED", "simulated", "Hôtel (Simulé)", True

    label = "Hôtel (Simulé)" if is_sim else "Hôtel (Partenaire Officiel)"
    return "HOTEL", sp, label, is_sim


def _compute_nearby_restaurants(
    acc_lat: float,
    acc_lng: float,
    restaurants: list[Place],
    max_radius_km: float = 5.0,
) -> list[NearbyRestaurantResponse]:
    nearby: list[NearbyRestaurantResponse] = []
    for rest in restaurants:
        dist_km = haversine_distance_km(acc_lat, acc_lng, rest.latitude, rest.longitude)
        if dist_km <= max_radius_km:
            dist_m = haversine_distance_m(acc_lat, acc_lng, rest.latitude, rest.longitude)
            nearby.append(
                NearbyRestaurantResponse(
                    id=rest.id,
                    name=rest.name,
                    description=rest.description,
                    latitude=rest.latitude,
                    longitude=rest.longitude,
                    estimated_cost=Decimal(str(rest.estimated_cost)).quantize(Decimal("0.01")),
                    price_tier=rest.price_tier,
                    avg_rating=rest.avg_rating,
                    hero_photos=rest.hero_photos or [],
                    distance_km=dist_km,
                    distance_m=dist_m,
                    walking_minutes=estimate_walking_minutes(dist_m),
                )
            )
    nearby.sort(key=lambda r: r.distance_m)
    return nearby


@router.get("/search", response_model=list[AccommodationSearchResponse])
async def search_accommodations_by_zone(
    response: Response,
    lat: float | None = Query(
        default=None,
        ge=-90.0,
        le=90.0,
        description="Latitude du centre de recherche (résolue depuis la destination du séjour si omise)",
    ),
    lng: float | None = Query(
        default=None,
        ge=-180.0,
        le=180.0,
        description="Longitude du centre de recherche (résolue depuis la destination du séjour si omise)",
    ),
    trip_id: str | None = Query(
        default=None,
        description="Identifiant du séjour pour centrer la recherche sur la destination du séjour",
    ),
    destination_id: str | None = Query(
        default=None,
        description="Identifiant de la destination pour centrer la recherche",
    ),
    radius_km: float = Query(default=15.0, gt=0.0, le=200.0, description="Rayon de recherche en km"),
    min_price: Decimal | None = Query(default=None, ge=Decimal("0.00")),
    max_price: Decimal | None = Query(default=None, ge=Decimal("0.00")),
    accommodation_type: str | None = Query(default=None, description="HOTEL ou AIRBNB"),
    luxury_tier: str | None = Query(default=None, description="ECONOMIC, STANDARD ou LUXURY"),
    restaurant_radius_km: float = Query(default=5.0, gt=0.0, le=50.0),
    db: AsyncSession = Depends(get_db),
) -> list[AccommodationSearchResponse]:
    if min_price is not None and max_price is not None and max_price < min_price:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Le prix maximum doit être supérieur ou égal au prix minimum.",
        )

    normalized_type = (accommodation_type or "").strip().upper()
    if normalized_type and normalized_type not in {
        AccommodationType.HOTEL.value,
        AccommodationType.AIRBNB.value,
    }:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Filtre accommodation_type invalide ('{accommodation_type}'). "
                "Valeurs acceptées : 'HOTEL', 'AIRBNB', ou omettre le paramètre pour tout afficher."
            ),
        )

    effective_lat: float | None = None
    effective_lng: float | None = None
    resolved_dest: Destination | None = None

    if lat is not None and lng is not None and trip_id is None and destination_id is None:
        effective_lat, effective_lng = lat, lng
    elif trip_id is not None:
        trip = await db.scalar(select(Trip).where(Trip.id == trip_id))
        if not trip:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Séjour introuvable.",
            )
        dest = await db.scalar(select(Destination).where(Destination.id == trip.destination_id))
        if not dest:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Destination du séjour introuvable.",
            )
        resolved_dest = dest
        effective_lat, effective_lng = (
            (lat, lng) if (lat is not None and lng is not None) else (dest.latitude, dest.longitude)
        )
    elif destination_id is not None:
        dest = await db.scalar(select(Destination).where(Destination.id == destination_id))
        if not dest:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Destination introuvable.",
            )
        resolved_dest = dest
        effective_lat, effective_lng = (
            (lat, lng) if (lat is not None and lng is not None) else (dest.latitude, dest.longitude)
        )
    else:
        active_trip = await db.scalar(
            select(Trip)
            .where(Trip.status == TripStatus.DRAFT.value)
            .order_by(Trip.created_at.desc())
            .limit(1)
        )
        if active_trip is None:
            active_trip = await db.scalar(
                select(Trip).order_by(Trip.created_at.desc()).limit(1)
            )
        if active_trip is not None:
            dest = await db.scalar(
                select(Destination).where(Destination.id == active_trip.destination_id)
            )
            if dest is not None:
                resolved_dest = dest
                effective_lat, effective_lng = dest.latitude, dest.longitude

        if effective_lat is None or effective_lng is None:
            effective_lat, effective_lng = 48.8566, 2.3522

    registry = get_provider_registry()
    provider_mode = registry.places.mode

    all_accommodations = list((await db.scalars(select(Accommodation))).all())
    all_restaurants = list(
        (
            await db.scalars(
                select(Place).where(Place.category == PlaceCategory.RESTAURANT.value)
            )
        ).all()
    )

    results: list[AccommodationSearchResponse] = []
    for acc in all_accommodations:
        dist_center = haversine_distance_km(
            effective_lat, effective_lng, acc.latitude, acc.longitude
        )
        if dist_center > radius_km:
            continue

        price_dec = Decimal(str(acc.price_per_night)).quantize(Decimal("0.01"))
        if min_price is not None and price_dec < min_price:
            continue
        if max_price is not None and price_dec > max_price:
            continue
        if normalized_type and acc.type.upper() != normalized_type:
            continue
        if luxury_tier and acc.luxury_tier.upper() != luxury_tier.upper():
            continue

        source_code, source_prov, source_label, is_sim = _build_source_metadata(
            acc.type, acc.source_provider, provider_mode
        )
        redirect_url = acc.booking_redirect_url or (
            f"https://www.airbnb.fr/s/homes?lat={acc.latitude}&lng={acc.longitude}"
            if acc.type.upper() == AccommodationType.AIRBNB.value
            else f"https://www.booking.com/searchresults.fr.html?latitude={acc.latitude}&longitude={acc.longitude}"
        )

        nearby_rests = _compute_nearby_restaurants(
            acc.latitude, acc.longitude, all_restaurants, max_radius_km=restaurant_radius_km
        )

        results.append(
            AccommodationSearchResponse(
                id=acc.id,
                destination_id=acc.destination_id,
                type=acc.type,
                source=source_code,
                source_provider=source_prov,
                source_label=source_label,
                provider_mode=provider_mode,
                is_simulated=is_sim,
                name=acc.name,
                neighborhood=acc.neighborhood,
                address=acc.address,
                latitude=acc.latitude,
                longitude=acc.longitude,
                distance_from_center_km=dist_center,
                price_per_night=price_dec,
                currency="EUR",
                luxury_tier=acc.luxury_tier,
                rating=acc.rating,
                photos=acc.photos or [],
                amenities=acc.amenities or [],
                booking_redirect_url=redirect_url,
                nearby_restaurants=nearby_rests,
            )
        )

    # En mode réel, si aucun Airbnb n'est présent dans la zone, on expose un lien partenaire/redirection Airbnb explicite
    if (
        provider_mode == "real"
        and not any(r.type == AccommodationType.AIRBNB.value for r in results)
        and (not accommodation_type or accommodation_type.upper() == AccommodationType.AIRBNB.value)
    ):
        partner_price = Decimal("160.00")
        if (min_price is None or partner_price >= min_price) and (
            max_price is None or partner_price <= max_price
        ):
            results.append(
                AccommodationSearchResponse(
                    id=f"airbnb-redirect-{round(effective_lat, 3)}-{round(effective_lng, 3)}",
                    destination_id="external",
                    type=AccommodationType.AIRBNB.value,
                    source="AIRBNB",
                    source_provider="airbnb_partner_redirect",
                    source_label="Airbnb (Redirection Partenaire / Agrégateur)",
                    provider_mode="real",
                    is_simulated=False,
                    name="Sélection Airbnb Zone Géographique (Redirection Partenaire)",
                    neighborhood=f"Zone ({effective_lat:.3f}, {effective_lng:.3f})",
                    address=f"Rayon {radius_km} km autour de ({effective_lat:.4f}, {effective_lng:.4f})",
                    latitude=effective_lat,
                    longitude=effective_lng,
                    distance_from_center_km=0.0,
                    price_per_night=partner_price,
                    currency="EUR",
                    luxury_tier=luxury_tier.upper() if luxury_tier else "STANDARD",
                    rating=4.8,
                    photos=[
                        "https://images.unsplash.com/photo-1502672260266-1c1ef2d93688?auto=format&fit=crop&w=1000&q=80"
                    ],
                    amenities=["Redirection directe Airbnb", "Logements entiers vérifiés"],
                    booking_redirect_url=f"https://www.airbnb.fr/s/homes?lat={effective_lat}&lng={effective_lng}",
                    nearby_restaurants=_compute_nearby_restaurants(
                        effective_lat,
                        effective_lng,
                        all_restaurants,
                        max_radius_km=restaurant_radius_km,
                    ),
                )
            )

    results.sort(key=lambda r: (r.distance_from_center_km, float(r.price_per_night)))
    if not results and provider_mode == "simulated":
        city_label_msg = resolved_dest.city_name if resolved_dest else "cette ville"
        response.headers["X-Simulation-Covered"] = "false"
        response.headers["X-Simulation-Message"] = (
            f"Les hébergements restent simulés : la ville de {city_label_msg} "
            "n'est pas couverte en simulation. Seules les 5 villes du seed (Paris, Tokyo, Rome, "
            "New York, Marrakech) disposent d'hébergements simulés."
        )
    else:
        response.headers["X-Simulation-Covered"] = "true"
    return results


@router.get(
    "/{accommodation_id}/nearby-restaurants",
    response_model=list[NearbyRestaurantResponse],
)
async def get_accommodation_nearby_restaurants(
    accommodation_id: str,
    radius_km: float = Query(default=5.0, gt=0.0, le=50.0),
    db: AsyncSession = Depends(get_db),
) -> list[NearbyRestaurantResponse]:
    acc = await db.scalar(select(Accommodation).where(Accommodation.id == accommodation_id))
    if not acc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hébergement introuvable.",
        )

    restaurants = list(
        (
            await db.scalars(
                select(Place).where(Place.category == PlaceCategory.RESTAURANT.value)
            )
        ).all()
    )
    return _compute_nearby_restaurants(acc.latitude, acc.longitude, restaurants, max_radius_km=radius_km)
