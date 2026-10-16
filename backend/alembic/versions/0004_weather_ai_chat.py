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


def downgrade() -> None:
    op.drop_column("chat_messages", "action_status")
    op.drop_column("chat_messages", "proposed_action")

    op.drop_column("itinerary_items", "weather_dismissed")
    op.drop_column("itinerary_items", "transit_time_source")
