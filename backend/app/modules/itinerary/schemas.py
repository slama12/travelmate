from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SuggestedSlotSchema(BaseModel):
    start_at: datetime
    end_at: datetime
    local_date: str
    local_start_time: str
    local_end_time: str
    timezone: str
    label: str


class ItineraryItemCreateRequest(BaseModel):
    trip_id: str
    place_id: str
    # Saisie soit par (visit_date + local_start_time dans le fuseau de la destination), soit par start_at (ISO UTC/offset)
    visit_date: date | None = None
    local_start_time: str | None = Field(
        default=None,
        description="Heure locale de début au format HH:MM dans le fuseau de la destination",
    )
    start_at: datetime | None = Field(
        default=None,
        description="Horodatage ISO complet (converti en UTC). Optionnel si visit_date + local_start_time sont fournis.",
    )
    duration_minutes: int | None = Field(
        default=None,
        ge=15,
        le=720,
        description="Durée en minutes (par défaut : durée conseillée du lieu)",
    )
    transit_mode: str = Field(default="METRO", description="WALKING, METRO ou CAR")
    notes: str | None = Field(default=None, max_length=500)
    allow_duplicate: bool = Field(
        default=False,
        description="Autorise explicitement la planification d'un même lieu une deuxième fois dans le séjour",
    )


class ItineraryItemUpdateRequest(BaseModel):
    visit_date: date | None = None
    local_start_time: str | None = None
    start_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=15, le=720)
    transit_mode: str | None = None
    notes: str | None = Field(default=None, max_length=500)


class ItineraryItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    trip_id: str
    place_id: str
    place_name: str
    place_category: str
    place_is_outdoor: bool = False
    place_latitude: float
    place_longitude: float
    recommended_duration_min: int
    opening_hours: dict[str, Any]
    visit_date: date
    start_at: datetime
    end_at: datetime
    local_visit_date: str
    local_start_time: str
    local_end_time: str
    destination_timezone: str
    duration_minutes: int
    transit_mode_to_next: str
    transit_duration_to_next_min: int
    transit_distance_meters: int
    transit_time_source: str = "ESTIMATED"
    transit_is_estimated: bool = True
    transit_source_label: str = "Temps estimé"
    transit_from_previous_min: int = 0
    transit_from_previous_m: int = 0
    google_calendar_event_id: str | None
    calendar_sync_status: str
    calendar_sync_attempts: int
    calendar_sync_error: str | None
    weather_warning: bool = False
    weather_dismissed: bool = False
    notes: str | None = None
    day_order_index: int


class TripItineraryScheduleResponse(BaseModel):
    trip_id: str
    destination_city: str
    destination_timezone: str
    trip_arrival_utc: datetime | None
    trip_departure_utc: datetime | None
    trip_arrival_local: str | None
    trip_departure_local: str | None
    total_visits: int
    total_transit_minutes: int
    total_distance_meters: int
    routing_mode: str = "simulated"
    routing_source_label: str = "Temps estimé"
    pending_calendar_sync_count: int
    items: list[ItineraryItemResponse]
    days: dict[str, list[ItineraryItemResponse]]


class OptimizeItineraryRequest(BaseModel):
    place_ids: list[str] | None = Field(
        default=None,
        description="Liste optionnelle de lieux à optimiser (par défaut : lieux déjà planifiés ou sélectionnés sur le voyage)",
    )
    default_transit_mode: str | None = Field(
        default=None,
        description="Mode de transport forcé (WALKING, METRO, CAR) ou choix automatique selon la distance si omis",
    )


class ProposedOptimizationSlotSchema(BaseModel):
    place_id: str
    place_name: str
    category: str
    visit_date: date
    local_start_time: str
    local_end_time: str
    start_at: datetime
    end_at: datetime
    duration_minutes: int
    day_cluster_index: int
    day_order_index: int
    transit_mode_from_prev: str
    transit_duration_from_prev_min: int
    transit_distance_from_prev_m: int
    transit_mode_to_next: str
    transit_duration_to_next_min: int
    transit_distance_meters: int
    validated_by_engine: bool


class OptimizeItineraryPreviewResponse(BaseModel):
    persisted: bool = False
    requires_user_confirmation: bool = True
    all_validated_by_engine: bool = True
    destination_timezone: str
    clusters_count: int
    total_places_scheduled: int
    unscheduled_places: list[str]
    current_total_transit_minutes: int
    current_total_distance_meters: int
    total_transit_minutes: int
    total_distance_meters: int
    proposed_items: list[ProposedOptimizationSlotSchema]


class ApplyOptimizationSlotInput(BaseModel):
    place_id: str
    visit_date: date | None = None
    local_start_time: str | None = None
    start_at: datetime | None = None
    duration_minutes: int = Field(..., ge=15, le=720)
    transit_mode_to_next: str = "METRO"


class ApplyOptimizationRequest(BaseModel):
    proposed_items: list[ApplyOptimizationSlotInput]
