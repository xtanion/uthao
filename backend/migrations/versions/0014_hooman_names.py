"""people are hoomans now, not residents

Only names the app assigned are touched. Someone who typed "Resident 1234"
themselves is indistinguishable, and renaming them is the cheaper mistake.


Revision ID: 0014_hooman_names
Revises: 0013_routing_record
"""
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0014_hooman_names'
down_revision: str | None = '0013_routing_record'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

users = sa.table('users', sa.column('id', sa.String), sa.column('display_name', sa.String))


def _rename(old_prefix: str, new_prefix: str, old_deleted: str, new_deleted: str) -> None:
    bind = op.get_bind()
    pattern = re.compile(rf'^{old_prefix} (\d{{4}})$')
    rows = bind.execute(
        sa.select(users.c.id, users.c.display_name).where(
            sa.or_(
                users.c.display_name.like(f'{old_prefix} ____'),
                users.c.display_name == old_deleted,
            )
        )
    ).all()
    for user_id, name in rows:
        if name == old_deleted:
            renamed = new_deleted
        elif match := pattern.match(name):
            renamed = f'{new_prefix} {match.group(1)}'
        else:
            continue
        bind.execute(users.update().where(users.c.id == user_id).values(display_name=renamed))


def upgrade() -> None:
    _rename('Resident', 'Hooman', 'Removed resident', 'Former hooman')


def downgrade() -> None:
    _rename('Hooman', 'Resident', 'Former hooman', 'Removed resident')
