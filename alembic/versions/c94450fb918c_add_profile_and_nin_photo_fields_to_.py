"""Add profile and NIN photo fields to Rider

Revision ID: c94450fb918c
Revises: 57a0ac249180
Create Date: 2024-11-11 23:05:15.713334

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers
revision: str = 'c94450fb918c'
down_revision: str = '57a0ac249180'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    # Get a list of columns in the 'riders' table
    columns = [col['name'] for col in inspector.get_columns('riders')]

    # Check if 'rider_photo' exists before adding it
    if 'rider_photo' not in columns:
        op.add_column('riders', sa.Column('rider_photo', sa.String(), nullable=True))

    # Check if 'nin_photo' exists before adding it
    if 'nin_photo' not in columns:
        op.add_column('riders', sa.Column('nin_photo', sa.String(), nullable=True))

def downgrade() -> None:
    op.drop_column('riders', 'nin_photo')
    op.drop_column('riders', 'rider_photo')