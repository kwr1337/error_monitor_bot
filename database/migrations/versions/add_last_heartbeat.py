"""add last_heartbeat column

Revision ID: add_last_heartbeat
Revises: 
Create Date: 2024-03-06 17:18:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_last_heartbeat'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('last_heartbeat', sa.DateTime, nullable=True))


def downgrade() -> None:
    op.drop_column('projects', 'last_heartbeat') 