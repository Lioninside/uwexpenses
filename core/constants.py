"""Shared sentinel values used across the workflow."""

# Stored in session.matches to indicate the user's decision for a transaction.
NO_RECEIPT = "__no_receipt__"    # business expense, no receipt exists
NEEDS_REVIEW = "__needs_review__"  # classification deferred for review
