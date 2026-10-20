"""Step 4 weather alerts, real/estimated transit source, and chat proposed actions

Revision ID: 0004_weather_ai_chat
Revises: 0003_planning_calendar
Create Date: 2026-10-15 20:25:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004_weather_ai_chat"
down_revision: str | None = "0003_planning_calendar"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "itinerary_items",
        sa.Column(
            "transit_time_source",
            sa.String(length=32),
            nullable=False,
            server_default="ESTIMATED",
        ),
    )
    op.add_column(
        "itinerary_items",
        sa.Column(
            "weather_dismissed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.add_column(
        "chat_messages",
        sa.Column("proposed_action", sa.JSON(), nullable=True),
    )
    op.add_column(
        "chat_messages",
        sa.Column(
            "action_status",
            sa.String(length=32),
            nullable=False,
            server_default="NONE",
        ),
    )

    op.create_table(
        "chat_unrecognized",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trip_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("raw_message", sa.Text(), nullable=False),
        sa.Column(
            "reason",
            sa.String(length=100),
            nullable=False,
            server_default="UNRECOGNIZED_INTENT",
        ),
        sa.Column(
            "assistant_reply",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_unrecognized_trip_id",
        "chat_unrecognized",
        ["trip_id"],
        unique=False,
    )
    op.create_index(
        "ix_chat_unrecognized_user_id",
        "chat_unrecognized",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_chat_unrecognized_user_id", table_name="chat_unrecognized")
    op.drop_index("ix_chat_unrecognized_trip_id", table_name="chat_unrecognized")
    op.drop_table("chat_unrecognized")

    op.drop_column("chat_messages", "action_status")
    op.drop_column("chat_messages", "proposed_action")

    op.drop_column("itinerary_items", "weather_dismissed")
    op.drop_column("itinerary_items", "transit_time_source")

