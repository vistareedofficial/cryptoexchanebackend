""" updated profile

Revision ID: 57a0ac249180
Revises: 00574ee0e5d1
Create Date: 2024-11-02 17:14:29.213706
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '57a0ac249180'
down_revision: Union[str, None] = '00574ee0e5d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Create the genderenum type if it doesn't exist
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'genderenum') THEN
                CREATE TYPE genderenum AS ENUM ('male', 'female');
            END IF;
        END
        $$;
    """)

    # Add the gender column to the users table
    op.add_column('users', sa.Column('gender', sa.Enum('male', 'female', name='genderenum'), nullable=True))


def downgrade() -> None:
    # Drop the gender column
    op.drop_column('users', 'gender')

    # Drop the genderenum type (if no longer needed)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'genderenum') THEN
                DROP TYPE genderenum;
            END IF;
        END
        $$;
    """)
