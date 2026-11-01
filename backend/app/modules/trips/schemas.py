from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import TravelStyle


class TripStageInput(BaseModel):
    order_index: int | None = None
    destination_id: str | None = None
    geoname_id: int | None = None
    city_name: str | None = None
    country: str | None = None
    country_name: str | None = "Monde"
    country_code_iso2: str | None = "XX"
    timezone: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    iata_code: str | None = None
    arrival_date: date
    nights: int = Field(default=2)
    departure_date: date | None = None
    arrival_at: datetime | None = None
    departure_at: datetime | None = None
    arrival_time_local: str | None = None
    departure_time_local: str | None = None
    arrival_transport_mode: str = Field(default="VOL")
    departure_transport_mode: str | None = None
    transport_unlocked: bool | None = None
    transport_booking_ref: str | None = None
    selected_place_ids: list[str] = Field(default_factory=list)
    planned_budget: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def _sync_country(self) -> "TripStageInput":
        if self.country and (not self.country_name or self.country_name == "Monde"):
            self.country_name = self.country
        if self.country_name and not self.country:
            self.country = self.country_name
        return self


class TripStageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    trip_id: str
    order_index: int
    destination_id: str
    geoname_id: int | None = None
    city_name: str
    country: str = ""
    country_name: str
    country_code_iso2: str
    timezone: str
    arrival_date: date
    nights: int
    departure_date: date
    arrival_at: datetime
    departure_at: datetime
    arrival_transport_mode: str
    departure_transport_mode: str | None = None
    arrival_buffer_hours: float = 2.0
    departure_buffer_hours: float = 3.0
    visit_window_start_utc: datetime | None = None
    visit_window_end_utc: datetime | None = None
    visit_window_start_local: str | None = None
    visit_window_end_local: str | None = None
    transport_unlocked: bool = False
    gallery_unlocked: bool = False
    transport_booking_ref: str | None = None
    selected_place_ids: list[str] = Field(default_factory=list)
    planned_budget: float | None = None
    created_at: datetime

    @model_validator(mode="after")
    def _sync_country_resp(self) -> "TripStageResponse":
        if not self.country and self.country_name:
            self.country = self.country_name
        return self


class TripStageBatchUpdateRequest(BaseModel):
    stages: list[TripStageInput]


class TripStageReorderRequest(BaseModel):
    stage_ids: list[str] | None = None
    ordered_stage_ids: list[str] | None = None
    recalculate_dates: bool = True

    @model_validator(mode="after")
    def _normalize_ids(self) -> "TripStageReorderRequest":
        if not self.stage_ids and self.ordered_stage_ids:
            self.stage_ids = list(self.ordered_stage_ids)
        return self


class TripStageConfirmTransportRequest(BaseModel):
    booking_reference: str | None = None
    transport_mode: str | None = None
    actual_cost: float | None = Field(default=None, ge=0.0)
    cost_amount: float | None = Field(default=None, ge=0.0)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    title: str | None = None

    @model_validator(mode="after")
    def _sync_cost(self) -> "TripStageConfirmTransportRequest":
        if self.actual_cost is None and self.cost_amount is not None:
            self.actual_cost = float(self.cost_amount)
        return self


class TripCreateRequest(BaseModel):
    destination_id: str | None = None
    origin_iata: str | None = None
    title: str = Field(default="Mon voyage", min_length=2, max_length=200)
    travel_style: TravelStyle = TravelStyle.STANDARD
    total_budget_planned: float = Field(default=1500.0, ge=0.0)
    total_budget: float | None = Field(default=None, ge=0.0)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    preferences: dict[str, Any] = Field(default_factory=lambda: {"culture": True, "food": True})
    arrival_at: datetime | None = None
    departure_at: datetime | None = None
    stages: list[TripStageInput] | None = None

    @model_validator(mode="after")
    def _sync_budget(self) -> "TripCreateRequest":
        if self.total_budget is not None and self.total_budget_planned == 1500.0:
            self.total_budget_planned = float(self.total_budget)
        return self


class TripResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_id: str
    destination_id: str
    title: str
    arrival_at: datetime | None
    departure_at: datetime | None
    travel_style: str
    total_budget_planned: float
    currency: str
    preferences: dict[str, Any]
    selected_place_ids: list[str] = Field(default_factory=list)
    status: str
    current_user_role: str = "OWNER"
    stages_count: int = 1
    is_multi_city: bool = False
    stages: list[TripStageResponse] = Field(default_factory=list)
    created_at: datetime



class TripMemberUpsertRequest(BaseModel):
    email: str | None = None
    user_id: str | None = None
    role: str = Field(default="VIEWER", description="OWNER, EDITOR ou VIEWER")


class TripMemberResponse(BaseModel):
    id: str
    trip_id: str
    user_id: str
    email: str
    full_name: str
    role: str
    role_label_fr: str
    invite_status: str
