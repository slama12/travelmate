from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select

from app.core.airports import OURAIRPORTS_CATALOG
from app.core.database import AsyncSession, get_db
from app.core.geo import estimate_walking_minutes, haversine_distance_km, haversine_distance_m
from app.core.providers import get_provider_registry
from app.core.seed import SEED_DESTINATIONS, get_seed_accommodation_meta
from app.models.entities import Accommodation, Destination, Place, Trip
from app.models.enums import AccommodationType, PlaceCategory, TravelStyle, TripStatus
from app.modules.accommodations.schemas import (
    AccommodationSearchResponse,
    NearbyRestaurantResponse,
)
from app.modules.places.world_place_photos_service import format_photo_credit
from app.modules.places.world_places_service import (
    build_accommodation_booking_urls,
    get_world_places_service,
)

router = APIRouter(prefix="/accommodations", tags=["Accommodations"])

_SEED_CITY_NAMES_LOWER = {str(d["city_name"]).strip().lower() for d in SEED_DESTINATIONS}


def _infer_accommodation_subtype(acc_type: str, name: str, meta_subtype: str | None = None) -> str:
    if meta_subtype:
        return meta_subtype
    low = (name or "").lower()
    if "riad" in low or "dar " in low:
        return "riad"
    if (acc_type or "").upper() == AccommodationType.AIRBNB.value or any(
        k in low for k in ("appartement", "loft", "studio", "maison", "villa", "résidence")
    ):
        return "appartement"
    return "hôtel"


def _infer_gamme_label(luxury_tier: str) -> str:
    tier_up = (luxury_tier or "STANDARD").upper()
    if tier_up == TravelStyle.ECONOMIC.value:
        return "Économique"
    if tier_up == TravelStyle.LUXURY.value:
        return "Luxe"
    return "Standard"


def _build_source_metadata(
    acc_type: str,
    source_provider: str | None,
    provider_mode: str,
) -> tuple[str, str, str, bool]:
    """
    Détermine la source explicite de chaque hébergement :
    - 'HOTEL' (hôtel officiel, Wikivoyage « Se loger » ou partenaire)
    - 'AIRBNB' (partenaire / agrégateur ou redirection Airbnb)
    - 'SIMULATED' (donnée de simulation locale)
    """
    sp = (source_provider or "simulated").lower()
    is_sim = provider_mode == "simulated" or sp == "simulated"

    if sp == "generic_fallback":
        return "HOTEL", "generic_fallback", "Carte générique • Booking / Airbnb", True

    if acc_type.upper() == AccommodationType.AIRBNB.value:
        source_code = "AIRBNB"
        if sp.startswith("wikivoyage"):
            return source_code, sp, "Wikivoyage « Se loger » • Airbnb / Booking", is_sim
        label = (
            "Airbnb (Simulé • Redirection Partenaire)"
            if is_sim
            else "Airbnb (Redirection Partenaire / Agrégateur)"
        )
        return source_code, "airbnb_partner_redirect", label, is_sim

    if sp.startswith("wikivoyage"):
        return "HOTEL", sp, "Wikivoyage « Se loger » • Booking / Airbnb", is_sim

    if sp == "simulated":
        return "SIMULATED", "simulated", "Hôtel (Simulé)", True

    label = "Hôtel (Simulé)" if is_sim else "Hôtel (Partenaire Officiel)"
    return "HOTEL", sp, label, is_sim


_LEGACY_CURATED_NAMES = {
    "ostello bello milano centrale",
    "appartement brera — navigli",
    "grand hotel et de milan",
    "hôtel mezri monastir",
    "appartement corniche de la falaise",
    "iberostar selection kuriat palace",
    "home lisbon hostel",
    "appartement azulejos alfama",
    "bairro alto hotel",
    "wake up! sydney central",
    "appartement vue port — the rocks",
    "park hyatt sydney",
    "slo living hostel lyon",
    "appartement canut croix-rousse",
    "villa florentine lyon",
}


def _is_legacy_invented_world_acc(name: str) -> bool:
    low = name.strip().lower()
    if low in _LEGACY_CURATED_NAMES:
        return True
    return any(
        low.startswith(prefix)
        for prefix in (
            "hôtel centre historique —",
            "appartement quartier central —",
            "grand hôtel & spa —",
        )
    )


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
    city_name: str | None = Query(
        default=None,
        description="Nom de la ville pour centrer la recherche",
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

    if lat is not None and lng is not None and trip_id is None and destination_id is None and city_name is None:
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
    elif city_name is not None:
        clean_city = city_name.strip().lower()
        all_dests_for_city = list((await db.scalars(select(Destination))).all())
        dest = next(
            (d for d in all_dests_for_city if d.city_name.strip().lower() == clean_city),
            None,
        )
        if dest is not None:
            resolved_dest = dest
            effective_lat, effective_lng = (
                (lat, lng) if (lat is not None and lng is not None) else (dest.latitude, dest.longitude)
            )
        else:
            effective_lat, effective_lng = (lat, lng) if (lat is not None and lng is not None) else (48.8566, 2.3522)
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

    all_destinations = list((await db.scalars(select(Destination))).all())
    dest_by_id: dict[str, Destination] = {d.id: d for d in all_destinations}
    if resolved_dest is None and effective_lat is not None and effective_lng is not None:
        nearest_dest: Destination | None = None
        nearest_dist = 999999.0
        for d in all_destinations:
            dist_d = haversine_distance_km(effective_lat, effective_lng, d.latitude, d.longitude)
            if dist_d < nearest_dist and dist_d <= max(radius_km, 35.0):
                nearest_dist = dist_d
                nearest_dest = d
        resolved_dest = nearest_dest

    registry = get_provider_registry()
    provider_mode = registry.places.mode

    all_accommodations = list((await db.scalars(select(Accommodation))).all())

    # Nettoie d'éventuelles anciennes lignes monde inventées en base
    stale_world_rows = [
        a
        for a in all_accommodations
        if _is_legacy_invented_world_acc(a.name)
    ]
    if stale_world_rows:
        for stale_row in stale_world_rows:
            await db.delete(stale_row)
            all_accommodations.remove(stale_row)
        await db.commit()

    # Pour les villes du monde (hors 5 villes de démo), peuple les hébergements depuis la section
    # « Se loger » de Wikivoyage si aucun hébergement n'est encore enregistré pour cette destination.
    if resolved_dest is not None:
        has_dest_accs = any(a.destination_id == resolved_dest.id for a in all_accommodations)
        if not has_dest_accs and resolved_dest.city_name.strip().lower() not in _SEED_CITY_NAMES_LOWER:
            wv_service = get_world_places_service()
            wv_accs = await wv_service.fetch_city_accommodations(
                city_name=resolved_dest.city_name,
                city_lat=resolved_dest.latitude,
                city_lon=resolved_dest.longitude,
                allow_network=True,
            )
            for wv_acc in wv_accs:
                new_acc = Accommodation(
                    destination_id=resolved_dest.id,
                    type=wv_acc.type,
                    name=wv_acc.name,
                    neighborhood=wv_acc.neighborhood,
                    address=wv_acc.address,
                    latitude=wv_acc.latitude,
                    longitude=wv_acc.longitude,
                    price_per_night=wv_acc.price_per_night,
                    luxury_tier=wv_acc.luxury_tier,
                    rating=wv_acc.rating,
                    photos=wv_acc.photos,
                    amenities=wv_acc.amenities,
                    source_provider=wv_acc.source_provider,
                    booking_redirect_url=wv_acc.booking_redirect_url,
                )
                db.add(new_acc)
                all_accommodations.append(new_acc)
            if wv_accs:
                await db.commit()

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

        acc_dest = dest_by_id.get(acc.destination_id) or resolved_dest
        city_name_for_links = acc_dest.city_name if acc_dest else "Ville"
        seed_meta = get_seed_accommodation_meta(acc.name)

        photos_list = [p for p in (acc.photos or []) if p and "unsplash.com" not in p.lower()]
        has_verified_photo = len(photos_list) > 0
        photo_author = seed_meta.get("photo_author") if has_verified_photo else None
        photo_license = seed_meta.get("photo_license") if has_verified_photo else None
        photo_file_title = seed_meta.get("photo_file_title") if has_verified_photo else None
        photo_commons_url = seed_meta.get("photo_commons_url") if has_verified_photo else None
        photo_source = str(seed_meta.get("photo_source") or ("wikipedia_pageimage" if has_verified_photo else "none"))
        external_entity_id = seed_meta.get("external_entity_id")
        credit_text = format_photo_credit(photo_author, photo_license) if has_verified_photo else None

        subtype = _infer_accommodation_subtype(
            acc.type,
            acc.name,
            seed_meta.get("accommodation_subtype"),
        )
        gamme_label = _infer_gamme_label(acc.luxury_tier)

        is_generic_fallback = (
            (acc.source_provider or "").lower() == "generic_fallback"
            or acc.name.strip().startswith("Hôtel de gamme ")
        )
        is_demo_city = (
            acc_dest is not None
            and acc_dest.city_name.strip().lower() in _SEED_CITY_NAMES_LOWER
        )
        has_precise_coords = (not is_generic_fallback) and (
            is_demo_city
            or acc_dest is None
            or not (
                abs(acc.latitude - acc_dest.latitude) < 1e-6
                and abs(acc.longitude - acc_dest.longitude) < 1e-6
            )
        )

        booking_url, airbnb_url = build_accommodation_booking_urls(
            name=acc.name,
            city_name=city_name_for_links,
            latitude=acc.latitude if has_precise_coords else None,
            longitude=acc.longitude if has_precise_coords else None,
            is_generic=is_generic_fallback,
        )

        source_code, source_prov, source_label, is_sim = _build_source_metadata(
            acc.type, acc.source_provider, provider_mode
        )
        redirect_url = acc.booking_redirect_url or (
            airbnb_url
            if acc.type.upper() == AccommodationType.AIRBNB.value
            else booking_url
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
                photos=photos_list,
                amenities=acc.amenities or [],
                booking_redirect_url=redirect_url,
                nearby_restaurants=nearby_rests,
                external_entity_id=external_entity_id,
                wikidata_id=external_entity_id,
                photo_file_title=photo_file_title,
                photo_author=photo_author,
                photo_license=photo_license,
                photo_commons_url=photo_commons_url,
                photo_source=photo_source,
                photo_credit_text=credit_text,
                accommodation_subtype=subtype,
                is_illustration=not has_verified_photo,
                illustration_label=None if has_verified_photo else "Illustration",
                price_label="Prix indicatif",
                gamme_label=gamme_label,
                has_precise_coords=has_precise_coords,
                booking_url=booking_url,
                airbnb_url=airbnb_url,
            )
        )

    # Si une recherche par coordonnées (lat, lng) vise une ville du monde non encore créée en base
    if not results and resolved_dest is None and effective_lat is not None and effective_lng is not None:
        nearest_airport = None
        nearest_airport_dist = 999999.0
        for rec in OURAIRPORTS_CATALOG:
            d_km = haversine_distance_km(effective_lat, effective_lng, rec.latitude, rec.longitude)
            if d_km < nearest_airport_dist and d_km <= 65.0:
                nearest_airport_dist = d_km
                nearest_airport = rec
        wv_accs = []
        if nearest_airport is not None and nearest_airport.municipality:
            wv_service = get_world_places_service()
            wv_accs = await wv_service.fetch_city_accommodations(
                city_name=nearest_airport.municipality,
                city_lat=effective_lat,
                city_lon=effective_lng,
                allow_network=True,
            )
        for idx, wv_acc in enumerate(wv_accs, start=1):
            dist_center = haversine_distance_km(
                effective_lat, effective_lng, wv_acc.latitude, wv_acc.longitude
            )
            if dist_center > radius_km:
                continue
            price_dec = Decimal(str(wv_acc.price_per_night)).quantize(Decimal("0.01"))
            if min_price is not None and price_dec < min_price:
                continue
            if max_price is not None and price_dec > max_price:
                continue
            if normalized_type and wv_acc.type.upper() != normalized_type:
                continue
            if luxury_tier and wv_acc.luxury_tier.upper() != luxury_tier.upper():
                continue
            source_code, source_prov, source_label, is_sim = _build_source_metadata(
                wv_acc.type, wv_acc.source_provider, provider_mode
            )
            results.append(
                AccommodationSearchResponse(
                    id=f"wv-sleep-{idx}-{round(wv_acc.latitude, 3)}",
                    destination_id="world-city",
                    type=wv_acc.type,
                    source=source_code,
                    source_provider=source_prov,
                    source_label=source_label,
                    provider_mode=provider_mode,
                    is_simulated=is_sim,
                    name=wv_acc.name,
                    neighborhood=wv_acc.neighborhood,
                    address=wv_acc.address,
                    latitude=wv_acc.latitude,
                    longitude=wv_acc.longitude,
                    distance_from_center_km=dist_center,
                    price_per_night=price_dec,
                    currency="EUR",
                    luxury_tier=wv_acc.luxury_tier,
                    rating=wv_acc.rating,
                    photos=[],
                    amenities=wv_acc.amenities,
                    booking_redirect_url=wv_acc.booking_redirect_url,
                    nearby_restaurants=_compute_nearby_restaurants(
                        wv_acc.latitude,
                        wv_acc.longitude,
                        all_restaurants,
                        max_radius_km=restaurant_radius_km,
                    ),
                    photo_source="none",
                    accommodation_subtype=wv_acc.accommodation_subtype,
                    is_illustration=True,
                    illustration_label="Illustration",
                    price_label="Prix indicatif",
                    gamme_label=wv_acc.gamme_label,
                    has_precise_coords=wv_acc.has_precise_coords,
                    booking_url=wv_acc.booking_url,
                    airbnb_url=wv_acc.airbnb_url,
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
            city_for_partner = resolved_dest.city_name if resolved_dest else "Séjour"
            b_url, a_url = build_accommodation_booking_urls(
                name=f"Appartement {city_for_partner}",
                city_name=city_for_partner,
                latitude=effective_lat,
                longitude=effective_lng,
            )
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
                    photos=[],
                    amenities=["Redirection directe Airbnb", "Logements entiers vérifiés"],
                    booking_redirect_url=a_url,
                    nearby_restaurants=_compute_nearby_restaurants(
                        effective_lat,
                        effective_lng,
                        all_restaurants,
                        max_radius_km=restaurant_radius_km,
                    ),
                    photo_source="none",
                    accommodation_subtype="appartement",
                    is_illustration=True,
                    illustration_label="Illustration",
                    price_label="Prix indicatif",
                    gamme_label=_infer_gamme_label(luxury_tier or "STANDARD"),
                    booking_url=b_url,
                    airbnb_url=a_url,
                )
            )

    results.sort(key=lambda r: (r.distance_from_center_km, float(r.price_per_night)))
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
