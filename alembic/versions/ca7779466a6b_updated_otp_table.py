"""updated otp table

Revision ID: ca7779466a6b
Revises: 00574ee0e5d1
Create Date: 2024-11-02 17:14:29.213706

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ca7779466a6b'
down_revision: Union[str, None] = '00574ee0e5d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum type only if it doesn't already exist
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'otptypeenum') THEN
            CREATE TYPE otptypeenum AS ENUM ('EMAIL', 'SMS');
        END IF;
    END
    $$;
    """)
    op.add_column('otp_verifications', sa.Column('otp_type', sa.Enum('EMAIL', 'SMS', name='otptypeenum'), nullable=False))


def downgrade() -> None:
    op.drop_column('otp_verifications', 'otp_type')
    # Optionally drop the enum type if you know it's no longer used elsewhere
    op.execute("DROP TYPE IF EXISTS otptypeenum")
