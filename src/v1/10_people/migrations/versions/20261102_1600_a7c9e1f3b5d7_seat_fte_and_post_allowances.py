"""seat FTE, over-budget role changes and post allowances on payslips

Revision ID: a7c9e1f3b5d7
Revises: f6b8d0e2a4c6
Create Date: 2026-11-02 16:00:00.000000+00:00

A seat is "filled" once its budgeted FTE is fully used, not as soon as one person sits in it:
seats that were filled by a single person keep that status, because their assignment uses 1.00 FTE.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7c9e1f3b5d7'
down_revision: Union[str, None] = 'f6b8d0e2a4c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('role_changes', sa.Column('over_budget', sa.Boolean(), server_default='0', nullable=False))
    op.add_column('payslips', sa.Column('post_allowance_pay', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False))
    op.add_column('payslips', sa.Column('post_allowance_lines', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('payslips', 'post_allowance_lines')
    op.drop_column('payslips', 'post_allowance_pay')
    op.drop_column('role_changes', 'over_budget')
