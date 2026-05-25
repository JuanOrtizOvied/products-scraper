"""add target_classification_id to job_queue

Revision ID: a1b2c3d4e5f6
Revises: d2c3476dee07
Create Date: 2026-05-06 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'd2c3476dee07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('job_queue') as batch_op:
        batch_op.add_column(
            sa.Column('target_classification_id', sa.Integer(), nullable=True),
        )
        batch_op.create_foreign_key(
            'fk_job_queue_target_cls', 'classifications',
            ['target_classification_id'], ['id'],
        )


def downgrade() -> None:
    with op.batch_alter_table('job_queue') as batch_op:
        batch_op.drop_constraint('fk_job_queue_target_cls', type_='foreignkey')
        batch_op.drop_column('target_classification_id')
