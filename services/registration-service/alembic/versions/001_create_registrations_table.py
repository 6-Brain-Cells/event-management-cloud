"""create registrations table

Revision ID: 001_registrations
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001_registrations"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS registrations (
            id SERIAL PRIMARY KEY,
            user_id INT NOT NULL,
            event_id INT NOT NULL,
            registration_date TIMESTAMP DEFAULT NOW(),
            status VARCHAR(20) DEFAULT 'confirmed',
            payment_method VARCHAR(50) DEFAULT 'free',
            payment_status VARCHAR(20) DEFAULT 'pending',
            payment_reference VARCHAR(100),
            payment_gateway VARCHAR(50),
            payment_processed_at TIMESTAMP,
            ticket_number VARCHAR(20) UNIQUE,
            notes TEXT,
            UNIQUE(user_id, event_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_reg_user ON registrations(user_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_reg_event_status ON registrations(event_id, status)"
    )


def downgrade() -> None:
    op.drop_index("idx_reg_event_status")
    op.drop_index("idx_reg_user")
    op.drop_table("registrations")
