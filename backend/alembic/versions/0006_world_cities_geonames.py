"""World cities step 1: geoname_id and population on destinations

Revision ID: 0006_world_cities_geonames
Revises: 0005_step5a_budget_docs_rbac
Create Date: 2026-10-26 12:00:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0006_world_cities_geonames"
down_revision: str | None = "0005_step5a_budget_docs_rbac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "destinations",
        sa.Column("geoname_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "destinations",
        sa.Column("population", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_destinations_geoname_id",
        "destinations",
        ["geoname_id"],
        unique=True,
    )

    # Renseigne les geoname_id et populations de référence des 5 villes du seed si déjà présentes
    seed_geonames = [
        ("Tokyo", 1850147, 8336599),
        ("Rome", 3169070, 2318895),
        ("New York", 5128581, 8804190),
        ("Marrakech", 2542997, 928850),
        ("Paris", 2988507, 2138551),
    ]
    conn = op.get_bind()
    for city_name, geoname_id, population in seed_geonames:
        conn.execute(
            sa.text(
                "UPDATE destinations SET geoname_id = :gid, population = :pop "
                "WHERE city_name = :city AND geoname_id IS NULL"
            ),
            {"gid": geoname_id, "pop": population, "city": city_name},
        )


def downgrade() -> None:
    op.drop_index("ix_destinations_geoname_id", table_name="destinations")
    op.drop_column("destinations", "population")
    op.drop_column("destinations", "geoname_id")
