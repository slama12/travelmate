"""Initial schema for TravelMate

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-10-14 10:55:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=150), nullable=False),
        sa.Column("preferred_style", sa.String(length=32), nullable=False),
        sa.Column("google_oauth_tokens", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "destinations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("city_name", sa.String(length=120), nullable=False),
        sa.Column("country_name", sa.String(length=120), nullable=False),
        sa.Column("country_code_iso2", sa.String(length=2), nullable=False),
        sa.Column("iata_code", sa.String(length=3), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("hero_image_url", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("practical_info", sa.JSON(), nullable=False),
        sa.Column("useful_phrases", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_destinations_city_name", "destinations", ["city_name"], unique=True)
    op.create_index("ix_destinations_iata_code", "destinations", ["iata_code"], unique=False)

    op.create_table(
        "trips",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("destination_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("arrival_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("departure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("travel_style", sa.String(length=32), nullable=False),
        sa.Column("total_budget_planned", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("preferences", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["destination_id"], ["destinations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trips_owner_id", "trips", ["owner_id"], unique=False)
    op.create_index("ix_trips_destination_id", "trips", ["destination_id"], unique=False)

    op.create_table(
        "trip_members",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trip_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("invite_status", sa.String(length=32), nullable=False),
        sa.Column("shared_calendar_id", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trip_members_trip_id", "trip_members", ["trip_id"], unique=False)
    op.create_index("ix_trip_members_user_id", "trip_members", ["user_id"], unique=False)

    op.create_table(
        "flight_bookings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trip_id", sa.String(length=36), nullable=False),
        sa.Column("pnr_reference", sa.String(length=16), nullable=False),
        sa.Column("airline", sa.String(length=100), nullable=False),
        sa.Column("flight_number_outbound", sa.String(length=20), nullable=False),
        sa.Column("flight_number_inbound", sa.String(length=20), nullable=False),
        sa.Column("origin_iata", sa.String(length=3), nullable=False),
        sa.Column("destination_iata", sa.String(length=3), nullable=False),
        sa.Column("departure_outbound_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("arrival_outbound_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("departure_inbound_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("arrival_inbound_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("cabin_class", sa.String(length=32), nullable=False),
        sa.Column("flight_status", sa.String(length=32), nullable=False),
        sa.Column("gmail_confirmation_sent", sa.Boolean(), nullable=False),
        sa.Column("gmail_message_id", sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_flight_bookings_trip_id", "flight_bookings", ["trip_id"], unique=False)
    op.create_index("ix_flight_bookings_pnr_reference", "flight_bookings", ["pnr_reference"], unique=True)

    op.create_table(
        "accommodations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("destination_id", sa.String(length=36), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("neighborhood", sa.String(length=120), nullable=False),
        sa.Column("address", sa.String(length=300), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("price_per_night", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("luxury_tier", sa.String(length=32), nullable=False),
        sa.Column("rating", sa.Float(), nullable=False),
        sa.Column("photos", sa.JSON(), nullable=False),
        sa.Column("amenities", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["destination_id"], ["destinations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_accommodations_destination_id", "accommodations", ["destination_id"], unique=False)
    op.create_index("ix_accommodations_geo", "accommodations", ["latitude", "longitude"], unique=False)

    op.create_table(
        "accommodation_bookings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trip_id", sa.String(length=36), nullable=False),
        sa.Column("accommodation_id", sa.String(length=36), nullable=False),
        sa.Column("check_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("check_out_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("confirmation_code", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(["accommodation_id"], ["accommodations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_accommodation_bookings_trip_id", "accommodation_bookings", ["trip_id"], unique=False
    )

    op.create_table(
        "places",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("destination_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("is_outdoor", sa.Boolean(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("recommended_duration_min", sa.Integer(), nullable=False),
        sa.Column("estimated_cost", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("price_tier", sa.String(length=32), nullable=False),
        sa.Column("avg_rating", sa.Float(), nullable=False),
        sa.Column("opening_hours", sa.JSON(), nullable=False),
        sa.Column("hero_photos", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["destination_id"], ["destinations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_places_destination_id", "places", ["destination_id"], unique=False)
    op.create_index("ix_places_geo", "places", ["latitude", "longitude"], unique=False)

    op.create_table(
        "itinerary_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trip_id", sa.String(length=36), nullable=False),
        sa.Column("place_id", sa.String(length=36), nullable=False),
        sa.Column("visit_date", sa.Date(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("transit_mode_to_next", sa.String(length=32), nullable=False),
        sa.Column("transit_duration_to_next_min", sa.Integer(), nullable=False),
        sa.Column("transit_distance_meters", sa.Integer(), nullable=False),
        sa.Column("google_calendar_event_id", sa.String(length=120), nullable=True),
        sa.Column("weather_warning", sa.Boolean(), nullable=False),
        sa.Column("suggested_replacement_place_id", sa.String(length=36), nullable=True),
        sa.Column("day_order_index", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["place_id"], ["places.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["suggested_replacement_place_id"], ["places.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_itinerary_items_trip_id", "itinerary_items", ["trip_id"], unique=False)
    op.create_index("ix_itinerary_items_place_id", "itinerary_items", ["place_id"], unique=False)
    op.create_index("ix_itinerary_items_visit_date", "itinerary_items", ["visit_date"], unique=False)

    op.create_table(
        "budget_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trip_id", sa.String(length=36), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("planned_amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("actual_amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("incurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_budget_items_trip_id", "budget_items", ["trip_id"], unique=False)

    op.create_table(
        "vault_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trip_id", sa.String(length=36), nullable=False),
        sa.Column("doc_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("encrypted_payload", sa.LargeBinary(), nullable=False),
        sa.Column("encryption_iv", sa.LargeBinary(), nullable=False),
        sa.Column("encrypted_dek", sa.LargeBinary(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vault_documents_trip_id", "vault_documents", ["trip_id"], unique=False)

    op.create_table(
        "place_votes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trip_id", sa.String(length=36), nullable=False),
        sa.Column("place_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("vote_value", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["place_id"], ["places.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_place_votes_trip_id", "place_votes", ["trip_id"], unique=False)

    op.create_table(
        "place_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("place_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("user_photos", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["place_id"], ["places.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_place_reviews_place_id", "place_reviews", ["place_id"], unique=False)

    op.create_table(
        "wishlist_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("place_id", sa.String(length=36), nullable=False),
        sa.Column("notes", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["place_id"], ["places.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wishlist_items_user_id", "wishlist_items", ["user_id"], unique=False)

    op.create_table(
        "alerts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trip_id", sa.String(length=36), nullable=False),
        sa.Column("alert_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_sent", sa.Boolean(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alerts_trip_id", "alerts", ["trip_id"], unique=False)

    op.create_table(
        "local_transports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("destination_id", sa.String(length=36), nullable=False),
        sa.Column("transport_type", sa.String(length=50), nullable=False),
        sa.Column("provider_name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("estimated_price_eur", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("booking_url", sa.String(length=500), nullable=False),
        sa.ForeignKeyConstraint(["destination_id"], ["destinations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_local_transports_destination_id", "local_transports", ["destination_id"], unique=False
    )

    op.create_table(
        "travel_journals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trip_id", sa.String(length=36), nullable=False),
        sa.Column("summary_markdown", sa.Text(), nullable=False),
        sa.Column("highlights", sa.JSON(), nullable=False),
        sa.Column("stats", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trip_id"),
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trip_id", sa.String(length=36), nullable=False),
        sa.Column("sender_role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_messages_trip_id", "chat_messages", ["trip_id"], unique=False)


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("travel_journals")
    op.drop_table("local_transports")
    op.drop_table("alerts")
    op.drop_table("wishlist_items")
    op.drop_table("place_reviews")
    op.drop_table("place_votes")
    op.drop_table("vault_documents")
    op.drop_table("budget_items")
    op.drop_table("itinerary_items")
    op.drop_table("places")
    op.drop_table("accommodation_bookings")
    op.drop_table("accommodations")
    op.drop_table("flight_bookings")
    op.drop_table("trip_members")
    op.drop_table("trips")
    op.drop_table("destinations")
    op.drop_table("users")
