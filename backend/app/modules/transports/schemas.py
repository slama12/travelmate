from decimal import Decimal
from pydantic import BaseModel, ConfigDict


class LocalTransportOptionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    transport_type: str  # VTC_TAXI, CAR_RENTAL, TRANSIT_PASS
    provider_name: str
    description: str
    estimated_price_eur: Decimal
    booking_url: str


class AirportTransferOptionSchema(BaseModel):
    mode: str  # METRO, CAR, VTC_TAXI
    label: str
    provider_name: str
    estimated_duration_min: int
    estimated_price_eur: Decimal
    distance_km: float
    booking_url: str
    notes: str


class AirportToAccommodationTransferResponse(BaseModel):
    city_name: str
    airport_iata: str
    airport_name: str
    accommodation_id: str | None = None
    accommodation_name: str
    accommodation_neighborhood: str
    distance_km: float
    recommended_mode: str
    options: list[AirportTransferOptionSchema]


class CityTransportsHubResponse(BaseModel):
    city_name: str
    country_name: str
    iata_code: str
    taxi_vtc_links: list[LocalTransportOptionSchema]
    car_rental_links: list[LocalTransportOptionSchema]
    transit_passes: list[LocalTransportOptionSchema]
    airport_transfer: AirportToAccommodationTransferResponse
