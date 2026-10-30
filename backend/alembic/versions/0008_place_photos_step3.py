"""Add Step 3 Commons photo metadata columns on places

Revision ID: 0008_place_photos_step3
Revises: 0007_world_places_step2
Create Date: 2026-10-28 15:40:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0008_place_photos_step3"
down_revision = "0007_world_places_step2"
branch_labels = None
depends_on = None


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(inspector, "places", "photo_file_title"):
        op.add_column("places", sa.Column("photo_file_title", sa.String(length=500), nullable=True))
    if not _has_column(inspector, "places", "photo_author"):
        op.add_column("places", sa.Column("photo_author", sa.String(length=500), nullable=True))
    if not _has_column(inspector, "places", "photo_license"):
        op.add_column("places", sa.Column("photo_license", sa.String(length=120), nullable=True))
    if not _has_column(inspector, "places", "photo_commons_url"):
        op.add_column("places", sa.Column("photo_commons_url", sa.String(length=1024), nullable=True))
    if not _has_column(inspector, "places", "photo_source"):
        op.add_column("places", sa.Column("photo_source", sa.String(length=80), nullable=True))
    if not _has_column(inspector, "places", "photo_checked_at"):
        op.add_column(
            "places",
            sa.Column("photo_checked_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for col in (
        "photo_checked_at",
        "photo_source",
        "photo_commons_url",
        "photo_license",
        "photo_author",
        "photo_file_title",
    ):
        if _has_column(inspector, "places", col):
            op.drop_column("places", col)
