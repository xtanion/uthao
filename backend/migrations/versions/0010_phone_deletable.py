"""closing an account nulls the phone rather than tombstoning it

A tombstone had to be unique, did not fit in a phone-sized column - which
SQLite let pass and PostgreSQL did not - and left something number-shaped
where a number used to be. The unique index permits many nulls on both
backends, so the number is simply given back.


Revision ID: 0010_phone_deletable
Revises: 0009_fix_date_time
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0010_phone_deletable'
down_revision: str | None = '0009_fix_date_time'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('phone',
               existing_type=sa.VARCHAR(length=20),
               nullable=True)



def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('phone',
               existing_type=sa.VARCHAR(length=20),
               nullable=False)

