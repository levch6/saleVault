"""one running run per site, process start time

Revision ID: 5d2e8a41c7b3
Revises: 8b45b97da1bc
Create Date: 2026-11-21 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5d2e8a41c7b3"
down_revision: str | None = "8b45b97da1bc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("scrape_runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("pid_start", sa.Integer(), nullable=True))
    # Keep only the newest running run per site before the unique index can be created.
    op.execute(
        """
        UPDATE scrape_runs
        SET status = 'failed', error = 'The scraper process ended unexpectedly'
        WHERE status = 'running'
          AND id NOT IN (SELECT max(id) FROM scrape_runs WHERE status = 'running' GROUP BY site_id)
        """
    )
    with op.batch_alter_table("scrape_runs", schema=None) as batch_op:
        batch_op.create_index(
            "uq_scrape_runs_one_running_per_site",
            ["site_id"],
            unique=True,
            sqlite_where=sa.text("status = 'running'"),
        )


def downgrade() -> None:
    with op.batch_alter_table("scrape_runs", schema=None) as batch_op:
        batch_op.drop_index("uq_scrape_runs_one_running_per_site")
        batch_op.drop_column("pid_start")
