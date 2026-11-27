"""Align indexes with report queries and remove unused duplicate indexes."""
from alembic import op

revision = "0003_query_performance"
down_revision = "0002_app_users"
branch_labels = None
depends_on = None


def upgrade():
    # The report filter selects by risk and then joins through transaction_id.
    op.create_index(
        "idx_results_risk_transaction",
        "screening_results",
        ["risk_level", "transaction_id"],
    )
    # These indexes had no matching query paths; current_hash is already unique.
    op.drop_index("idx_transactions_customer", table_name="transactions")
    op.drop_index("idx_transactions_created", table_name="transactions")
    op.drop_index("idx_results_risk", table_name="screening_results")
    op.drop_index("idx_audit_hash", table_name="audit_logs")


def downgrade():
    op.create_index("idx_transactions_customer", "transactions", ["normalized_name"])
    op.create_index("idx_transactions_created", "transactions", ["created_at"])
    op.create_index("idx_results_risk", "screening_results", ["risk_level"])
    op.create_index("idx_audit_hash", "audit_logs", ["current_hash"])
    op.drop_index("idx_results_risk_transaction", table_name="screening_results")
