"""Initial authenticated briefing schema."""
from alembic import op

from app.database import Base
from app import models  # noqa: F401

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())
    op.create_index("ix_audit_event_created", "audit_event", ["created_at"])
    op.create_index("ix_brief_run_status", "brief_run", ["status"])
    op.create_index("ix_brief_run_article_run", "brief_run_article", ["run_id"])
    op.create_index("ix_watch_item_status", "watch_item", ["status"])


def downgrade() -> None:
    # Production migrations are forward-only so audit and operational records survive.
    pass
