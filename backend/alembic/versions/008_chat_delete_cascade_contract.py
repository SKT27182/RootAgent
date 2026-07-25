"""Document external-first deletion contract for all delete paths.

Revision ID: 008
Revises: 007

Postgres FKs already cascade:
  user → chats → chat_runs + artifacts

Application wipe order (session_service / artifact_service):
  1. MinIO (file or prefix)
  2. Redis session keys / local workspaces when applicable
  3. DELETE Postgres row last so ON DELETE CASCADE clears children

Paths covered:
  - DELETE chat/session
  - DELETE user (admin)
  - DELETE single artifact
  - Generated overwrite of duplicate same-chat filenames
"""

from collections.abc import Sequence

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Cascades already applied in 001/005. External-first wipe is enforced in
    # application services; no DDL required for a fresh deploy.
    pass


def downgrade() -> None:
    pass
