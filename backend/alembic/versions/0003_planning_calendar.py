"""Step 3 itinerary calendar sync and post-commit email status

Revision ID: 0003_planning_calendar
Revises: 0002_booking_geo
Create Date: 2026-10-14 13:32:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0003_planning_calendar"
down_revision: str | None = "0002_booking_geo"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "flight_bookings",
        sa.Column("gmail_send_status", sa.String(length=32), nullable=False, server_default="PENDING"),
    )
    op.add_column(
        "flight_bookings",
        sa.Column("gmail_send_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "flight_bookings",
        sa.Column("gmail_last_error", sa.Text(), nullable=True),
    )

    op.add_column(
        "itinerary_items",
        sa.Column(
            "calendar_sync_status",
            sa.String(length=32),
            nullable=False,
            server_default="PENDING_SYNC",
        ),
    )
    op.add_column(
        "itinerary_items",
        sa.Column("calendar_sync_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "itinerary_items",
        sa.Column("calendar_sync_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "itinerary_items",
        sa.Column("notes", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("itinerary_items", "notes")
    op.drop_column("itinerary_items", "calendar_sync_error")
    op.drop_column("itinerary_items", "calendar_sync_attempts")
    op.drop_column("itinerary_items", "calendar_sync_status")

    op.drop_column("flight_bookings", "gmail_last_error")
    op.drop_column("flight_bookings", "gmail_send_attempts")
    op.drop_column("flight_bookings", "gmail_send_status")
