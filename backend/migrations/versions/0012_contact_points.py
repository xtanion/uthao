"""departmental and ward desks inside an authority

A corporation's front door is not where a complaint is worked. Mumbai routes
a pothole to the roads engineer and a blocked drain to storm water drains, and
each of its 24 wards has its own assistant commissioner. Departments route by
category and are live; wards route by geometry we do not have yet and are
carried inactive so the addresses survive until it lands.


Revision ID: 0012_contact_points
Revises: 0011_authorities
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0012_contact_points'
down_revision: str | None = '0011_authorities'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('authority_contact_points',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('authority_id', sa.String(length=32), nullable=False),
    sa.Column('kind', sa.Enum('department', 'ward', name='contactpointkind', native_enum=False, length=32), nullable=False),
    sa.Column('key', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('source_url', sa.String(length=500), nullable=True),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['authority_id'], ['authorities.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('authority_id', 'kind', 'key', name='uq_contact_point')
    )


def downgrade() -> None:
    op.drop_table('authority_contact_points')
