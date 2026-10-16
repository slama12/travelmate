from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PlaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    destination_id: str
    city_name: str
    name: str
    description: str
    category: str
    is_outdoor: bool
    latitude: float
    longitude: float
    recommended_duration_min: int
    estimated_cost: Decimal
    price_tier: str
    avg_rating: float
    opening_hours: dict[str, Any] = Field(default_factory=dict)
    hero_photos: list[str] = Field(default_factory=list)
    source_provider: str = "simulated"
    is_wishlisted: bool = False
    is_selected_for_trip: bool = False


class CityPlacesResultResponse(BaseModel):
    city_name: str
    provider_mode: str
    cached_in_redis: bool = False
    available_in_current_mode: bool = True
    message: str | None = None
    places: list[PlaceResponse] = Field(default_factory=list)


class TripGalleryResponse(BaseModel):
    trip_id: str
    city_name: str
    unlocked: bool
    unlock_message: str
    provider_mode: str
    cached_in_redis: bool = False
    selected_place_ids: list[str] = Field(default_factory=list)
    places: list[PlaceResponse] = Field(default_factory=list)


class TripPlaceSelectionRequest(BaseModel):
    place_id: str
    selected: bool = True


class WishlistToggleRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=300)


class WishlistToggleResponse(BaseModel):
    place_id: str
    wishlisted: bool
    notes: str | None = None
    total_wishlist_count: int
