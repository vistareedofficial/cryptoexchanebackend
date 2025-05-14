"""Add profile and NIN photo fields to Rider

Revision ID: c94450fb918c
Revises: 57a0ac249180
Create Date: 2024-11-11 23:05:15.713334

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c94450fb918c'
down_revision: Union[str, None] = '57a0ac249180'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add the columns with correct types (if they don't exist already)
    op.add_column('riders', sa.Column('rider_photo', sa.String(), nullable=True))
    op.add_column('riders', sa.Column('nin_photo', sa.String(), nullable=True))


def downgrade() -> None:
    # Drop the columns if rolling back
    op.drop_column('riders', 'nin_photo')
    op.drop_column('riders', 'rider_photo')
