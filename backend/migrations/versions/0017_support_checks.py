"""support checks: photo hashes, verification times, a reason on notifications

Everything already stored is marked verified at the time it was made, so no
report loses its confirmations on deploy.

Revision ID: 0017_support_checks
Revises: 0016_review
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0017_support_checks'
down_revision: str | None = '0016_review'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('supports', schema=None) as batch_op:
        batch_op.add_column(sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table('issue_photos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('dhash', sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table('activity_events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('note', sa.String(length=300), nullable=True))

    op.execute("UPDATE supports SET verified_at = created_at")
    op.execute("UPDATE issue_photos SET verified_at = created_at")


def downgrade() -> None:
    with op.batch_alter_table('activity_events', schema=None) as batch_op:
        batch_op.drop_column('note')
    with op.batch_alter_table('issue_photos', schema=None) as batch_op:
        batch_op.drop_column('verified_at')
        batch_op.drop_column('dhash')
    with op.batch_alter_table('supports', schema=None) as batch_op:
        batch_op.drop_column('verified_at')
