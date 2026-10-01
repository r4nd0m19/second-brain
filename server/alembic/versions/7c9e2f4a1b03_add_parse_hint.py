"""add parse hint

Revision ID: 7c9e2f4a1b03
Revises: 59ddc1fed5de
Create Date: 2026-10-01 23:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '7c9e2f4a1b03'
down_revision: Union[str, Sequence[str], None] = '59ddc1fed5de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('documents', sa.Column('parse_hint', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('documents', 'parse_hint')
