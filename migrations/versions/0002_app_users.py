"""Add authentication principals and roles."""
from alembic import op
import sqlalchemy as sa

revision = "0002_app_users"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_users",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("username", sa.Text(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('ADMINISTRATOR','ANALYST','AUDITOR')"),
    )


def downgrade():
    op.drop_table("app_users")
