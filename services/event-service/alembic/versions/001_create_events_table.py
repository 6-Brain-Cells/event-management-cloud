"""create events table

Revision ID: 001_events
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001_events"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id SERIAL PRIMARY KEY,
            title VARCHAR(200) NOT NULL,
            description TEXT,
            event_type VARCHAR(50) NOT NULL,
            start_date TIMESTAMP NOT NULL,
            end_date TIMESTAMP NOT NULL,
            location VARCHAR(200),
            max_capacity INT NOT NULL DEFAULT 100,
            registered_count INT DEFAULT 0,
            organizer_id INT NOT NULL,
            ticket_price DECIMAL(10,2) DEFAULT 0.00,
            status VARCHAR(20) DEFAULT 'active',
            version INT NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_status_type ON events(status, event_type)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_events_start_date ON events(start_date)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_organizer ON events(organizer_id)"
    )
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='events' AND column_name='version'
            ) THEN
                ALTER TABLE events ADD COLUMN version INT NOT NULL DEFAULT 1;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_index("idx_events_organizer")
    op.drop_index("idx_events_start_date")
    op.drop_index("idx_events_status_type")
    op.drop_table("events")
