"""merge multiple heads into one

Revision ID: 7b5920d066ea
Revises: 0ec3efeb7c8e, b7be5f768661
Create Date: 2025-05-14 00:16:00.119659

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7b5920d066ea'
down_revision: Union[str, None] = ('0ec3efeb7c8e', 'b7be5f768661')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
