"""authorities live in a table rather than one address in the environment

AUTHORITY_EMAIL was a single global address for the whole of India. Bodies
change their grievance contacts, and most publish a portal rather than an
inbox, so this is a row per body carrying what it actually accepts. The
setting stays as the fallback for a deployment with an empty table.


Revision ID: 0011_authorities
Revises: 0010_phone_deletable
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0011_authorities'
down_revision: str | None = '0010_phone_deletable'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'authorities',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('slug', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('city', sa.String(length=80), nullable=False),
        sa.Column('state', sa.String(length=80), nullable=False),
        sa.Column(
            'channel',
            sa.Enum('email', 'portal', 'none', name='contactchannel', native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column('email', sa.String(length=320), nullable=True),
        sa.Column('portal_url', sa.String(length=500), nullable=True),
        sa.Column('helpline', sa.String(length=40), nullable=True),
        sa.Column('min_latitude', sa.Float(), nullable=False),
        sa.Column('max_latitude', sa.Float(), nullable=False),
        sa.Column('min_longitude', sa.Float(), nullable=False),
        sa.Column('max_longitude', sa.Float(), nullable=False),
        sa.Column('source_url', sa.String(length=500), nullable=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug'),
    )
    op.create_index(
        'ix_authorities_box', 'authorities', ['min_latitude', 'max_latitude'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_authorities_box', table_name='authorities')
    op.drop_table('authorities')
