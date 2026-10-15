"""AI review gate: a note for rejected reports

The two new statuses (in_review, rejected) need no DDL: status is stored as a
32-character string, not a native enum. Existing reports keep their status, so
nothing already public is pulled back into review.

Revision ID: 0016_review
Revises: 0015_push
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0016_review'
down_revision: str | None = '0015_push'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('issues', schema=None) as batch_op:
        batch_op.add_column(sa.Column('review_note', sa.String(length=300), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('issues', schema=None) as batch_op:
        batch_op.drop_column('review_note')
