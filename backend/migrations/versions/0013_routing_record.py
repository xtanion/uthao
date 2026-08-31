"""what a letter was routed as, and to which desk

The recipient alone does not say why it was chosen. When an address turns out
to be the wrong one, this is what connects it back to the decision.


Revision ID: 0013_routing_record
Revises: 0012_contact_points
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0013_routing_record'
down_revision: str | None = '0012_contact_points'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('escalations', sa.Column('routed_category', sa.String(length=40), nullable=True))
    op.add_column('escalations', sa.Column('routed_desk', sa.String(length=160), nullable=True))


def downgrade() -> None:
    op.drop_column('escalations', 'routed_desk')
    op.drop_column('escalations', 'routed_category')
