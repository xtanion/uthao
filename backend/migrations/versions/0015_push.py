"""push notifications: device tokens, and which activity has been pushed

Rows that already exist are marked pushed. They have been in the feed for as
long as they have existed, and a phone buzzing for each of them on the first
deploy would be noise, not news.


Revision ID: 0015_push
Revises: 0014_hooman_names
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0015_push'
down_revision: str | None = '0014_hooman_names'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('push_tokens',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('token', sa.String(length=200), nullable=False),
    sa.Column('platform', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token')
    )
    with op.batch_alter_table('push_tokens', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_push_tokens_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('activity_events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pushed_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index('ix_activity_pushed_created', ['pushed_at', 'created_at'], unique=False)

    events = sa.table('activity_events', sa.column('pushed_at'), sa.column('created_at'))
    op.execute(events.update().values(pushed_at=events.c.created_at))



def downgrade() -> None:
    with op.batch_alter_table('activity_events', schema=None) as batch_op:
        batch_op.drop_index('ix_activity_pushed_created')
        batch_op.drop_column('pushed_at')

    with op.batch_alter_table('push_tokens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_push_tokens_user_id'))

    op.drop_table('push_tokens')
