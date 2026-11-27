"""Initial PostgreSQL schema matching the SQLite V2 model."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("transactions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("transaction_ref", sa.Text(), nullable=False, unique=True),
        sa.Column("customer_name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("source_file", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount > 0"))
    op.create_table("watchlist",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False, unique=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("risk_weight", sa.Integer(), nullable=False),
        sa.CheckConstraint("risk_weight BETWEEN 1 AND 100"))
    op.create_table("screening_results",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("transaction_id", sa.BigInteger(), sa.ForeignKey("transactions.id"), nullable=False, unique=True),
        sa.Column("watchlist_id", sa.BigInteger(), sa.ForeignKey("watchlist.id")),
        sa.Column("match_type", sa.Text(), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=False),
        sa.Column("risk_level", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("screened_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("audit_logs",
        sa.Column("event_id", sa.BigInteger(), primary_key=True),
        sa.Column("timestamp", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("previous_hash", sa.Text(), nullable=False),
        sa.Column("current_hash", sa.Text(), nullable=False, unique=True))
    op.create_table("processed_files",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False, unique=True),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("idx_transactions_customer", "transactions", ["normalized_name"])
    op.create_index("idx_transactions_created", "transactions", ["created_at"])
    op.create_index("idx_results_risk", "screening_results", ["risk_level"])
    op.create_index("idx_audit_hash", "audit_logs", ["current_hash"])


def downgrade():
    op.drop_index("idx_audit_hash", table_name="audit_logs")
    op.drop_index("idx_results_risk", table_name="screening_results")
    op.drop_index("idx_transactions_created", table_name="transactions")
    op.drop_index("idx_transactions_customer", table_name="transactions")
    op.drop_table("processed_files")
    op.drop_table("audit_logs")
    op.drop_table("screening_results")
    op.drop_table("watchlist")
    op.drop_table("transactions")
