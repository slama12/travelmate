"""Step 2 booking and geospatial columns

Revision ID: 0002_booking_geo
Revises: 0001_initial_schema
Create Date: 2026-10-14 11:30:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002_booking_geo"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "trips",
        sa.Column("selected_place_ids", sa.JSON(), nullable=False, server_default="[]"),
    )

    op.add_column(
        "flight_bookings",
        sa.Column("idempotency_key", sa.String(length=100), nullable=False, server_default="legacy"),
    )
    op.add_column(
        "flight_bookings",
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="EUR"),
    )
    op.add_column(
        "flight_bookings",
        sa.Column("vault_document_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "flight_bookings",
        sa.Column("budget_item_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "flight_bookings",
        sa.Column("confirmation_email_preview", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_flight_bookings_idempotency_key", "flight_bookings", ["idempotency_key"], unique=True)

    op.add_column(
        "accommodations",
        sa.Column("source_provider", sa.String(length=50), nullable=False, server_default="simulated"),
    )
    op.add_column(
        "accommodations",
        sa.Column("booking_redirect_url", sa.String(length=500), nullable=True),
    )

    op.add_column(
        "places",
        sa.Column("source_provider", sa.String(length=50), nullable=False, server_default="simulated"),
    )
    op.add_column(
        "places",
        sa.Column("external_place_id", sa.String(length=120), nullable=True),
    )
    op.create_index("ix_places_external_place_id", "places", ["external_place_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_places_external_place_id", table_name="places")
    op.drop_column("places", "external_place_id")
    op.drop_column("places", "source_provider")

    op.drop_column("accommodations", "booking_redirect_url")
    op.drop_column("accommodations", "source_provider")

    op.drop_index("ix_flight_bookings_idempotency_key", table_name="flight_bookings")
    op.drop_column("flight_bookings", "confirmation_email_preview")
    op.drop_column("flight_bookings", "budget_item_id")
    op.drop_column("flight_bookings", "vault_document_id")
    op.drop_column("flight_bookings", "currency")
    op.drop_column("flight_bookings", "idempotency_key")

    op.drop_column("trips", "selected_place_ids")
