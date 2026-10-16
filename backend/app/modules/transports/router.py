from decimal import Decimal
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.database import AsyncSession, get_db
from app.core.geo import estimate_transit_duration_min, haversine_distance_km
from app.models.entities import Accommodation, Destination, LocalTransport, Trip
from app.modules.transports.schemas import (
    AirportToAccommodationTransferResponse,
    AirportTransferOptionSchema,
    CityTransportsHubResponse,
    LocalTransportOptionSchema,
)

router = APIRouter(prefix="/transports", tags=["Local Transports & Airport Transfer"])

AIRPORT_METADATA: dict[str, dict[str, Any]] = {
    "CDG": {
        "name": "Aéroport Paris-Charles de Gaulle (CDG)",
        "latitude": 49.0097,
        "longitude": 2.5479,
        "rail_name": "RER B Express / RoissyBus",
        "rail_price_eur": Decimal("11.80"),
        "rail_url": "https://www.iledefrance-mobilites.fr",
        "taxi_name": "Forfait Taxi Officiel G7 / Uber CDG",
        "taxi_fixed_eur": Decimal("56.00"),
        "taxi_url": "https://www.g7.fr",
    },
    "HND": {
        "name": "Aéroport International de Tokyo-Haneda (HND)",
        "latitude": 35.5494,
        "longitude": 139.7798,
        "rail_name": "Tokyo Monorail + JR Yamanote / Keikyu Line",
        "rail_price_eur": Decimal("4.20"),
        "rail_url": "https://www.tokyo-monorail.co.jp/english/",
        "taxi_name": "GO Taxi Japan / Uber Tokyo",
        "taxi_fixed_eur": Decimal("52.00"),
        "taxi_url": "https://go.goinc.jp/",
    },
    "FCO": {
        "name": "Aéroport Léonard-de-Vinci de Rome Fiumicino (FCO)",
        "latitude": 41.8003,
        "longitude": 12.2389,
        "rail_name": "Leonardo Express (Trenitalia FCO -> Termini)",
        "rail_price_eur": Decimal("14.00"),
        "rail_url": "https://www.trenitalia.com",
        "taxi_name": "Taxi Blanc Officiel Comune di Roma / FreeNow",
        "taxi_fixed_eur": Decimal("50.00"),
        "taxi_url": "https://www.free-now.com/it/",
    },
    "JFK": {
        "name": "Aéroport International John-F.-Kennedy (JFK)",
        "latitude": 40.6413,
        "longitude": -73.7781,
        "rail_name": "AirTrain JFK + Subway (E / A) ou LIRR",
        "rail_price_eur": Decimal("10.80"),
        "rail_url": "https://new.mta.info/guides/airports/jfk",
        "taxi_name": "NYC Yellow Cab Flat Fare / Uber & Lyft",
        "taxi_fixed_eur": Decimal("68.00"),
        "taxi_url": "https://www.uber.com/global/en/Airports/jfk/",
    },
    "RAK": {
        "name": "Aéroport Marrakech-Ménara (RAK)",
        "latitude": 31.6069,
        "longitude": -8.0363,
        "rail_name": "Navette Bus Aéroport L19 ALSA (Jemaa el-Fna)",
        "rail_price_eur": Decimal("3.00"),
        "rail_url": "https://www.alsa.ma/marrakech",
        "taxi_name": "Guichet Officiel Taxi Aéroport RAK / Careem",
        "taxi_fixed_eur": Decimal("10.00"),
        "taxi_url": "https://www.careem.com",
    },
}

DEFAULT_CAR_RENTALS: dict[str, dict[str, Any]] = {
    "Paris": {
        "provider_name": "Sixt & Europcar Aéroport Paris-CDG",
        "description": "Location citadine ou berline hybride avec retrait au Terminal 2 CDG et assurance tous risques.",
        "estimated_price_eur": Decimal("49.00"),
        "booking_url": "https://www.sixt.fr/location-voiture/france/paris/",
    },
    "Tokyo": {
        "provider_name": "Toyota Rent a Car Tokyo Haneda",
        "description": "Location véhicule hybride avec GPS multilingue et carte ETC autoroutes japonaises.",
        "estimated_price_eur": Decimal("58.00"),
        "booking_url": "https://rent.toyota.co.jp/eng/",
    },
    "Rome": {
        "provider_name": "Hertz & Maggiore Rome Fiumicino",
        "description": "Location Fiat 500e ou compacte compatible ZTL électrique au départ de Fiumicino.",
        "estimated_price_eur": Decimal("42.00"),
        "booking_url": "https://www.hertz.it",
    },
    "New York": {
        "provider_name": "Avis & Enterprise JFK Airport",
        "description": "Location SUV ou berline avec badge E-ZPass inclus au Federal Circle Station JFK.",
        "estimated_price_eur": Decimal("74.00"),
        "booking_url": "https://www.avis.com/en/locations/us/ny/queens/jfk",
    },
    "Marrakech": {
        "provider_name": "Europcar & Hertz Marrakech-Ménara",
        "description": "Location citadine climatisée ou 4x4 pour excursions dans l'Atlas au départ du Terminal 1.",
        "estimated_price_eur": Decimal("32.00"),
        "booking_url": "https://www.europcar.ma",
    },
}


def _build_airport_transfer(
    destination: Destination,
    accommodation: Accommodation | None,
) -> AirportToAccommodationTransferResponse:
    iata = (destination.iata_code or "INT").upper()
    airport = AIRPORT_METADATA.get(
        iata,
        {
            "name": f"Aéroport International de {destination.city_name} ({iata})",
            "latitude": destination.latitude + 0.14,
            "longitude": destination.longitude + 0.14,
            "rail_name": f"Train Express / Navette Aéroport {destination.city_name}",
            "rail_price_eur": Decimal("10.00"),
            "rail_url": f"https://www.google.com/maps/dir/?api=1&destination={quote(destination.city_name)}",
            "taxi_name": f"Taxi Officiel & Uber {destination.city_name}",
            "taxi_fixed_eur": Decimal("45.00"),
            "taxi_url": "https://www.uber.com",
        },
    )

    target_lat = accommodation.latitude if accommodation else destination.latitude
    target_lng = accommodation.longitude if accommodation else destination.longitude
    acc_name = accommodation.name if accommodation else f"Centre-ville de {destination.city_name}"
    acc_neighborhood = (
        accommodation.neighborhood if accommodation else destination.city_name
    )

    dist_km = haversine_distance_km(
        airport["latitude"], airport["longitude"], target_lat, target_lng
    )
    # Facteur de détour routier/ferroviaire réaliste (~1.25x la distance à vol d'oiseau)
    road_dist_km = round(max(4.5, dist_km * 1.25), 1)

    metro_duration = max(20, estimate_transit_duration_min(road_dist_km, "METRO") + 5)
    taxi_duration = max(15, estimate_transit_duration_min(road_dist_km, "CAR"))
    car_duration = max(15, taxi_duration - 2)

    car_rental_meta = DEFAULT_CAR_RENTALS.get(
        destination.city_name,
        {
            "provider_name": f"Sixt / Europcar Aéroport {destination.city_name}",
            "estimated_price_eur": Decimal("45.00"),
            "booking_url": "https://www.sixt.fr",
        },
    )

    options = [
        AirportTransferOptionSchema(
            mode="METRO",
            label="Transport en commun / Train Express Aéroport",
            provider_name=airport["rail_name"],
            estimated_duration_min=metro_duration,
            estimated_price_eur=airport["rail_price_eur"],
            distance_km=road_dist_km,
            booking_url=airport["rail_url"],
            notes=f"Liaison directe depuis {airport['name']} vers {acc_neighborhood}.",
        ),
        AirportTransferOptionSchema(
            mode="VTC_TAXI",
            label="Taxi Officiel / VTC Porte-à-Porte",
            provider_name=airport["taxi_name"],
            estimated_duration_min=taxi_duration,
            estimated_price_eur=airport["taxi_fixed_eur"],
            distance_km=road_dist_km,
            booking_url=airport["taxi_url"],
            notes=f"Prise en charge au terminal d'arrivée jusqu'à « {acc_name} ».",
        ),
        AirportTransferOptionSchema(
            mode="CAR",
            label="Location de voiture dès l'aéroport (prix / jour)",
            provider_name=car_rental_meta["provider_name"],
            estimated_duration_min=car_duration,
            estimated_price_eur=car_rental_meta["estimated_price_eur"],
            distance_km=road_dist_km,
            booking_url=car_rental_meta["booking_url"],
            notes="Retrait du véhicule au comptoir loueurs de l'aéroport.",
        ),
    ]

    recommended_mode = "VTC_TAXI" if road_dist_km <= 12.0 else "METRO"
    return AirportToAccommodationTransferResponse(
        city_name=destination.city_name,
        airport_iata=iata,
        airport_name=airport["name"],
        accommodation_id=accommodation.id if accommodation else None,
        accommodation_name=acc_name,
        accommodation_neighborhood=acc_neighborhood,
        distance_km=road_dist_km,
        recommended_mode=recommended_mode,
        options=options,
    )


async def _build_city_transports_hub(
    db: AsyncSession,
    destination: Destination,
    accommodation_id: str | None = None,
) -> CityTransportsHubResponse:
    db_transports = list(
        (
            await db.scalars(
                select(LocalTransport).where(LocalTransport.destination_id == destination.id)
            )
        ).all()
    )

    # S'assure que chaque ville possède aussi une option CAR_RENTAL en base
    has_car_rental = any(t.transport_type == "CAR_RENTAL" for t in db_transports)
    if not has_car_rental:
        car_meta = DEFAULT_CAR_RENTALS.get(
            destination.city_name,
            {
                "provider_name": f"Sixt & Europcar {destination.city_name}",
                "description": f"Location de voiture avec retrait à l'aéroport ({destination.iata_code}) ou en centre-ville.",
                "estimated_price_eur": Decimal("45.00"),
                "booking_url": "https://www.sixt.fr",
            },
        )
        car_tr = LocalTransport(
            destination_id=destination.id,
            transport_type="CAR_RENTAL",
            provider_name=car_meta["provider_name"],
            description=car_meta["description"],
            estimated_price_eur=float(car_meta["estimated_price_eur"]),
            booking_url=car_meta["booking_url"],
        )
        db.add(car_tr)
        await db.commit()
        await db.refresh(car_tr)
        db_transports.append(car_tr)

    taxi_vtc: list[LocalTransportOptionSchema] = []
    car_rentals: list[LocalTransportOptionSchema] = []
    transit_passes: list[LocalTransportOptionSchema] = []

    for tr in db_transports:
        schema_item = LocalTransportOptionSchema(
            id=tr.id,
            transport_type=tr.transport_type,
            provider_name=tr.provider_name,
            description=tr.description,
            estimated_price_eur=Decimal(str(tr.estimated_price_eur)).quantize(Decimal("0.01")),
            booking_url=tr.booking_url,
        )
        if tr.transport_type == "VTC_TAXI":
            taxi_vtc.append(schema_item)
        elif tr.transport_type == "CAR_RENTAL":
            car_rentals.append(schema_item)
        else:
            transit_passes.append(schema_item)

    accommodation: Accommodation | None = None
    if accommodation_id:
        accommodation = await db.scalar(
            select(Accommodation).where(Accommodation.id == accommodation_id)
        )
    if not accommodation:
        accommodation = await db.scalar(
            select(Accommodation)
            .where(Accommodation.destination_id == destination.id)
            .order_by(Accommodation.rating.desc())
        )

    airport_transfer = _build_airport_transfer(destination, accommodation)

    return CityTransportsHubResponse(
        city_name=destination.city_name,
        country_name=destination.country_name,
        iata_code=destination.iata_code,
        taxi_vtc_links=taxi_vtc,
        car_rental_links=car_rentals,
        transit_passes=transit_passes,
        airport_transfer=airport_transfer,
    )


@router.get("/city/{city_name}", response_model=CityTransportsHubResponse)
async def get_city_transports(
    city_name: str,
    accommodation_id: str | None = Query(
        default=None,
        description="Identifiant optionnel de l'hébergement pour calculer le trajet exact depuis l'aéroport",
    ),
    db: AsyncSession = Depends(get_db),
) -> CityTransportsHubResponse:
    destination = await db.scalar(
        select(Destination).where(func.lower(Destination.city_name) == city_name.strip().lower())
    )
    if not destination:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Destination '{city_name}' introuvable.",
        )
    return await _build_city_transports_hub(db, destination, accommodation_id=accommodation_id)


@router.get("/trip/{trip_id}", response_model=CityTransportsHubResponse)
async def get_trip_transports(
    trip_id: str,
    accommodation_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> CityTransportsHubResponse:
    trip = await db.scalar(select(Trip).where(Trip.id == trip_id))
    if not trip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voyage introuvable.",
        )
    destination = await db.scalar(select(Destination).where(Destination.id == trip.destination_id))
    if not destination:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Destination introuvable.",
        )
    return await _build_city_transports_hub(db, destination, accommodation_id=accommodation_id)
