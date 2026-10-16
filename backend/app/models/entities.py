from datetime import date, datetime, timezone
from typing import Any
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import (
    AccommodationType,
    AlertType,
    BudgetCategory,
    CabinClass,
    DocumentType,
    FlightStatus,
    InviteStatus,
    MemberRole,
    PlaceCategory,
    TransitMode,
    TravelStyle,
    TripStatus,
)


def _uuid_str() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    preferred_style: Mapped[str] = mapped_column(
        String(32), default=TravelStyle.STANDARD.value, nullable=False
    )
    google_oauth_tokens: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    trips: Mapped[list["Trip"]] = relationship(
        "Trip", back_populates="owner", cascade="all, delete-orphan"
    )
    memberships: Mapped[list["TripMember"]] = relationship(
        "TripMember", back_populates="user", cascade="all, delete-orphan"
    )
    reviews: Mapped[list["PlaceReview"]] = relationship(
        "PlaceReview", back_populates="user", cascade="all, delete-orphan"
    )
    wishlist_items: Mapped[list["WishlistItem"]] = relationship(
        "WishlistItem", back_populates="user", cascade="all, delete-orphan"
    )


class Destination(Base):
    __tablename__ = "destinations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    city_name: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    country_name: Mapped[str] = mapped_column(String(120), nullable=False)
    country_code_iso2: Mapped[str] = mapped_column(String(2), nullable=False)
    iata_code: Mapped[str] = mapped_column(String(3), index=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    hero_image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    practical_info: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    useful_phrases: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

    trips: Mapped[list["Trip"]] = relationship("Trip", back_populates="destination")
    places: Mapped[list["Place"]] = relationship(
        "Place", back_populates="destination", cascade="all, delete-orphan"
    )
    accommodations: Mapped[list["Accommodation"]] = relationship(
        "Accommodation", back_populates="destination", cascade="all, delete-orphan"
    )
    local_transports: Mapped[list["LocalTransport"]] = relationship(
        "LocalTransport", back_populates="destination", cascade="all, delete-orphan"
    )


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    destination_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("destinations.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    arrival_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    departure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    travel_style: Mapped[str] = mapped_column(
        String(32), default=TravelStyle.STANDARD.value, nullable=False
    )
    total_budget_planned: Mapped[float] = mapped_column(Numeric(12, 2), default=1500.0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    preferences: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    selected_place_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=TripStatus.DRAFT.value, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    owner: Mapped["User"] = relationship("User", back_populates="trips")
    destination: Mapped["Destination"] = relationship("Destination", back_populates="trips")
    members: Mapped[list["TripMember"]] = relationship(
        "TripMember", back_populates="trip", cascade="all, delete-orphan"
    )
    flight_bookings: Mapped[list["FlightBooking"]] = relationship(
        "FlightBooking", back_populates="trip", cascade="all, delete-orphan"
    )
    accommodation_bookings: Mapped[list["AccommodationBooking"]] = relationship(
        "AccommodationBooking", back_populates="trip", cascade="all, delete-orphan"
    )
    itinerary_items: Mapped[list["ItineraryItem"]] = relationship(
        "ItineraryItem", back_populates="trip", cascade="all, delete-orphan"
    )
    budget_items: Mapped[list["BudgetItem"]] = relationship(
        "BudgetItem", back_populates="trip", cascade="all, delete-orphan"
    )
    vault_documents: Mapped[list["VaultDocument"]] = relationship(
        "VaultDocument", back_populates="trip", cascade="all, delete-orphan"
    )
    place_votes: Mapped[list["PlaceVote"]] = relationship(
        "PlaceVote", back_populates="trip", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["Alert"]] = relationship(
        "Alert", back_populates="trip", cascade="all, delete-orphan"
    )
    chat_messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage", back_populates="trip", cascade="all, delete-orphan"
    )
    journal: Mapped["TravelJournal | None"] = relationship(
        "TravelJournal", back_populates="trip", uselist=False, cascade="all, delete-orphan"
    )


class TripMember(Base):
    __tablename__ = "trip_members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    trip_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trips.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), default=MemberRole.VIEWER.value, nullable=False)
    invite_status: Mapped[str] = mapped_column(
        String(32), default=InviteStatus.PENDING.value, nullable=False
    )
    shared_calendar_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    trip: Mapped["Trip"] = relationship("Trip", back_populates="members")
    user: Mapped["User"] = relationship("User", back_populates="memberships")


class FlightBooking(Base):
    __tablename__ = "flight_bookings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    trip_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trips.id", ondelete="CASCADE"), index=True, nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    pnr_reference: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    airline: Mapped[str] = mapped_column(String(100), nullable=False)
    flight_number_outbound: Mapped[str] = mapped_column(String(20), nullable=False)
    flight_number_inbound: Mapped[str] = mapped_column(String(20), nullable=False)
    origin_iata: Mapped[str] = mapped_column(String(3), nullable=False)
    destination_iata: Mapped[str] = mapped_column(String(3), nullable=False)
    departure_outbound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    arrival_outbound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    departure_inbound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    arrival_inbound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    cabin_class: Mapped[str] = mapped_column(String(32), default=CabinClass.ECONOMY.value, nullable=False)
    flight_status: Mapped[str] = mapped_column(
        String(32), default=FlightStatus.SCHEDULED.value, nullable=False
    )
    vault_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    budget_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    gmail_confirmation_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    gmail_send_status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    gmail_send_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gmail_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    gmail_message_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    confirmation_email_preview: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    trip: Mapped["Trip"] = relationship("Trip", back_populates="flight_bookings")


class Accommodation(Base):
    __tablename__ = "accommodations"
    __table_args__ = (Index("ix_accommodations_geo", "latitude", "longitude"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    destination_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("destinations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    type: Mapped[str] = mapped_column(String(32), default=AccommodationType.HOTEL.value, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    neighborhood: Mapped[str] = mapped_column(String(120), nullable=False)
    address: Mapped[str] = mapped_column(String(300), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    price_per_night: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    luxury_tier: Mapped[str] = mapped_column(String(32), default=TravelStyle.STANDARD.value, nullable=False)
    rating: Mapped[float] = mapped_column(Float, default=4.5, nullable=False)
    photos: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    amenities: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    source_provider: Mapped[str] = mapped_column(String(50), default="simulated", nullable=False)
    booking_redirect_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    destination: Mapped["Destination"] = relationship("Destination", back_populates="accommodations")


class AccommodationBooking(Base):
    __tablename__ = "accommodation_bookings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    trip_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trips.id", ondelete="CASCADE"), index=True, nullable=False
    )
    accommodation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accommodations.id", ondelete="RESTRICT"), nullable=False
    )
    check_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    check_out_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    confirmation_code: Mapped[str] = mapped_column(String(40), nullable=False)

    trip: Mapped["Trip"] = relationship("Trip", back_populates="accommodation_bookings")
    accommodation: Mapped["Accommodation"] = relationship("Accommodation")


class Place(Base):
    __tablename__ = "places"
    __table_args__ = (Index("ix_places_geo", "latitude", "longitude"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    destination_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("destinations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(32), default=PlaceCategory.CULTURE.value, nullable=False)
    is_outdoor: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    recommended_duration_min: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    estimated_cost: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0, nullable=False)
    price_tier: Mapped[str] = mapped_column(String(32), default=TravelStyle.STANDARD.value, nullable=False)
    avg_rating: Mapped[float] = mapped_column(Float, default=4.7, nullable=False)
    opening_hours: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    hero_photos: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    source_provider: Mapped[str] = mapped_column(String(50), default="simulated", nullable=False)
    external_place_id: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)

    destination: Mapped["Destination"] = relationship("Destination", back_populates="places")
    itinerary_items: Mapped[list["ItineraryItem"]] = relationship(
        "ItineraryItem",
        back_populates="place",
        foreign_keys="ItineraryItem.place_id",
    )
    reviews: Mapped[list["PlaceReview"]] = relationship(
        "PlaceReview", back_populates="place", cascade="all, delete-orphan"
    )


class ItineraryItem(Base):
    __tablename__ = "itinerary_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    trip_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trips.id", ondelete="CASCADE"), index=True, nullable=False
    )
    place_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("places.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    visit_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    transit_mode_to_next: Mapped[str] = mapped_column(
        String(32), default=TransitMode.METRO.value, nullable=False
    )
    transit_duration_to_next_min: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    transit_distance_meters: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    transit_time_source: Mapped[str] = mapped_column(String(32), default="ESTIMATED", nullable=False)
    google_calendar_event_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    calendar_sync_status: Mapped[str] = mapped_column(String(32), default="PENDING_SYNC", nullable=False)
    calendar_sync_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    calendar_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    weather_warning: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    weather_dismissed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    suggested_replacement_place_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("places.id", ondelete="SET NULL"), nullable=True
    )
    day_order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    trip: Mapped["Trip"] = relationship("Trip", back_populates="itinerary_items")
    place: Mapped["Place"] = relationship(
        "Place", back_populates="itinerary_items", foreign_keys=[place_id]
    )


class BudgetItem(Base):
    __tablename__ = "budget_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    trip_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trips.id", ondelete="CASCADE"), index=True, nullable=False
    )
    category: Mapped[str] = mapped_column(
        String(32), default=BudgetCategory.ACTIVITY.value, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    planned_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0, nullable=False)
    actual_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    incurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    trip: Mapped["Trip"] = relationship("Trip", back_populates="budget_items")


class VaultDocument(Base):
    __tablename__ = "vault_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    trip_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trips.id", ondelete="CASCADE"), index=True, nullable=False
    )
    doc_type: Mapped[str] = mapped_column(
        String(32), default=DocumentType.FLIGHT_TICKET.value, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), default="application/pdf", nullable=False)
    encrypted_payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encryption_iv: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encrypted_dek: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    trip: Mapped["Trip"] = relationship("Trip", back_populates="vault_documents")


class PlaceVote(Base):
    __tablename__ = "place_votes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    trip_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trips.id", ondelete="CASCADE"), index=True, nullable=False
    )
    place_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("places.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    vote_value: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    trip: Mapped["Trip"] = relationship("Trip", back_populates="place_votes")


class PlaceReview(Base):
    __tablename__ = "place_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    place_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("places.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    user_photos: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    place: Mapped["Place"] = relationship("Place", back_populates="reviews")
    user: Mapped["User"] = relationship("User", back_populates="reviews")


class WishlistItem(Base):
    __tablename__ = "wishlist_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    place_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("places.id", ondelete="CASCADE"), index=True, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="wishlist_items")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    trip_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trips.id", ondelete="CASCADE"), index=True, nullable=False
    )
    alert_type: Mapped[str] = mapped_column(
        String(32), default=AlertType.VISIT_REMINDER.value, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    trip: Mapped["Trip"] = relationship("Trip", back_populates="alerts")


class LocalTransport(Base):
    __tablename__ = "local_transports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    destination_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("destinations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    transport_type: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_price_eur: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    booking_url: Mapped[str] = mapped_column(String(500), nullable=False)

    destination: Mapped["Destination"] = relationship("Destination", back_populates="local_transports")


class TravelJournal(Base):
    __tablename__ = "travel_journals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    trip_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trips.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    summary_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    highlights: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    trip: Mapped["Trip"] = relationship("Trip", back_populates="journal")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    trip_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trips.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sender_role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_action: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    action_status: Mapped[str] = mapped_column(String(32), default="NONE", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    trip: Mapped["Trip"] = relationship("Trip", back_populates="chat_messages")
