from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class NearbyRestaurantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    latitude: float
    longitude: float
    estimated_cost: Decimal
    price_tier: str
    avg_rating: float
    hero_photos: list[str] = Field(default_factory=list)
    distance_km: float
    distance_m: int
    walking_minutes: int


class AccommodationSearchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    destination_id: str
    type: str
    source: str
    source_provider: str
    source_label: str
    provider_mode: str
    is_simulated: bool
    name: str
    neighborhood: str
    address: str
    latitude: float
    longitude: float
    distance_from_center_km: float
    price_per_night: Decimal
    currency: str = "EUR"
    luxury_tier: str
    rating: float
    photos: list[str] = Field(default_factory=list)
    amenities: list[str] = Field(default_factory=list)
    booking_redirect_url: str
    nearby_restaurants: list[NearbyRestaurantResponse] = Field(default_factory=list)
