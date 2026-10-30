"""Add Step 2 world places columns and cache index on places

Revision ID: 0007_world_places_step2
Revises: 0006_world_cities_geonames
Create Date: 2026-10-28 10:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0007_world_places_step2"
down_revision = "0006_world_cities_geonames"
branch_labels = None
depends_on = None


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(inspector, "places", "address"):
        op.add_column("places", sa.Column("address", sa.String(length=255), nullable=True))
    if not _has_column(inspector, "places", "website_url"):
        op.add_column("places", sa.Column("website_url", sa.String(length=500), nullable=True))
    if not _has_column(inspector, "places", "price_label"):
        op.add_column("places", sa.Column("price_label", sa.String(length=120), nullable=True))
    if not _has_column(inspector, "places", "hours_status"):
        op.add_column("places", sa.Column("hours_status", sa.String(length=60), nullable=True))
    if not _has_column(inspector, "places", "source_url"):
        op.add_column("places", sa.Column("source_url", sa.String(length=500), nullable=True))
    if not _has_column(inspector, "places", "source_attribution"):
        op.add_column("places", sa.Column("source_attribution", sa.String(length=255), nullable=True))
    if not _has_column(inspector, "places", "notoriety_score"):
        op.add_column(
            "places",
            sa.Column("notoriety_score", sa.Integer(), server_default="0", nullable=False),
        )

    if not _has_index(inspector, "places", "ix_places_dest_source_ext"):
        op.create_index(
            "ix_places_dest_source_ext",
            "places",
            ["destination_id", "source_provider", "external_place_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(inspector, "places", "ix_places_dest_source_ext"):
        op.drop_index("ix_places_dest_source_ext", table_name="places")
    for col in (
        "notoriety_score",
        "source_attribution",
        "source_url",
        "hours_status",
        "price_label",
        "website_url",
        "address",
    ):
        if _has_column(inspector, "places", col):
            op.drop_column("places", col)
